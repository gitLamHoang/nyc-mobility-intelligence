"""Paired block resampling of saved development errors; no fitting or raw-data access."""

import json
import subprocess
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd

from nyc_mobility.config import TIMEZONE, write_json
from nyc_mobility.data.download import sha256
from nyc_mobility.evaluation.splits import local_boundary


def validate_daily_errors(
    daily: pd.DataFrame, backtest: dict, sealed_test_start: str
) -> tuple[list[str], list[tuple[np.ndarray, np.ndarray]]]:
    """Return aligned day counts and model MAEs after full coverage/reconciliation checks."""
    required = {"fold", "date_nyc", "model", "rows", "mae"}
    if set(daily) != required or daily.empty or daily.isna().any().any():
        raise ValueError("Daily errors require a complete, nonempty schema")
    if daily.duplicated(["fold", "date_nyc", "model"]).any():
        raise ValueError("Duplicate fold/date/model errors")
    dates = pd.to_datetime(daily.date_nyc, format="%Y-%m-%d", errors="raise")
    if not dates.dt.strftime("%Y-%m-%d").eq(daily.date_nyc).all():
        raise ValueError("Daily dates must be ISO NYC calendar dates")
    numeric = daily[["rows", "mae"]].to_numpy(dtype=float)
    if not np.isfinite(numeric).all() or (numeric < 0).any():
        raise ValueError("Daily counts and errors must be finite and nonnegative")
    if backtest["protocol"]["study"]["sealed_test_start"] != sealed_test_start:
        raise ValueError("Backtest and current dataset disagree on the sealed test boundary")
    if backtest["test_metrics"] is not None:
        raise ValueError("Uncertainty stage accepts development-only backtests")
    names = list(backtest["pooled_metrics"])
    records = backtest["folds"]
    fold_names = [fold["name"] for fold in records]
    if not records or len(fold_names) != len(set(fold_names)):
        raise ValueError("Backtest must have unique nonempty folds")
    if set(daily.fold) != set(fold_names) or set(daily.model) != set(names):
        raise ValueError("Daily errors do not cover the recorded folds/models")
    arrays, previous_end, zone_count = [], None, None
    for fold in records:
        start = pd.Timestamp(fold["validation_start"]).tz_convert(TIMEZONE)
        end = pd.Timestamp(fold["validation_end"]).tz_convert(TIMEZONE)
        if (
            start != start.normalize()
            or end != end.normalize()
            or start >= end
            or end > local_boundary(sealed_test_start)
            or (previous_end is not None and start < previous_end)
        ):
            raise ValueError("Validation folds must be chronological development calendar days")
        previous_end = end
        hours = (end - start).total_seconds() / 3600
        zones = fold["validation_rows"] / hours
        if zones <= 0 or zones != int(zones) or (zone_count is not None and zones != zone_count):
            raise ValueError("Fold coverage does not describe a consistent zone/hour grid")
        zone_count = int(zones)
        boundaries = pd.date_range(start, end, freq="D")
        day_names = boundaries[:-1].strftime("%Y-%m-%d").tolist()
        weights = np.array(
            [
                int((right - left).total_seconds() / 3600) * zone_count
                for left, right in zip(boundaries[:-1], boundaries[1:], strict=True)
            ]
        )
        frame = daily.loc[daily.fold == fold["name"]]
        if len(frame) != len(day_names) * len(names) or set(frame.date_nyc) != set(day_names):
            raise ValueError("Daily errors have missing or extra validation dates/models")
        row_matrix = frame.pivot(index="date_nyc", columns="model", values="rows").reindex(
            index=day_names, columns=names
        )
        if not np.equal(row_matrix.to_numpy(), weights[:, None]).all():
            raise ValueError("Daily zone/hour coverage differs across models or ignores DST")
        losses = (
            frame.pivot(index="date_nyc", columns="model", values="mae")
            .reindex(index=day_names, columns=names)
            .to_numpy(dtype=float)
        )
        observed = np.average(losses, weights=weights, axis=0)
        expected = np.array([fold["metrics"][name]["mae"] for name in names])
        if not np.allclose(observed, expected, rtol=1e-10, atol=1e-12):
            raise ValueError("Daily errors do not reconcile with fold MAE")
        arrays.append((weights, losses))
    total_rows = sum(weights.sum() for weights, _ in arrays)
    if total_rows != backtest["validation_rows"]:
        raise ValueError("Daily row counts do not reconcile with pooled coverage")
    observed = (
        sum((weights[:, None] * losses).sum(axis=0) for weights, losses in arrays) / total_rows
    )
    expected = np.array([backtest["pooled_metrics"][name]["mae"] for name in names])
    if not np.allclose(observed, expected, rtol=1e-10, atol=1e-12):
        raise ValueError("Daily errors do not reconcile with pooled MAE")
    return names, arrays


def circular_indices(
    days: int, block_days: int, replicates: int, rng: np.random.Generator
) -> np.ndarray:
    """Draw fixed-length wrapping blocks and trim each replicate to the fold's day count."""
    if any(type(value) is not int or value <= 0 for value in [days, block_days, replicates]):
        raise ValueError("Day counts, block length and replicates must be positive integers")
    if block_days > days:
        raise ValueError("Block length cannot exceed a fold's day count")
    starts = rng.integers(days, size=(replicates, (days + block_days - 1) // block_days))
    blocks = (starts[:, :, None] + np.arange(block_days)) % days
    return blocks.reshape(replicates, -1)[:, :days]


def bootstrap_mae(
    folds: list[tuple[np.ndarray, np.ndarray]], block_days: int, replicates: int, seed: int
) -> np.ndarray:
    """Share draws across models and weight sampled days by their actual forecast rows."""
    rng = np.random.default_rng(np.random.SeedSequence([seed, block_days]))
    errors = np.zeros((replicates, folds[0][1].shape[1]))
    counts = np.zeros(replicates)
    for weights, losses in folds:
        indices = circular_indices(len(weights), block_days, replicates, rng)
        sampled_weights = weights[indices]
        errors += (losses[indices] * sampled_weights[:, :, None]).sum(axis=1)
        counts += sampled_weights.sum(axis=1)
    return errors / counts[:, None]


def compare_draws(draws: np.ndarray, point: np.ndarray, names: list[str], protocol: dict) -> list:
    confidence = protocol["study"]["confidence_level"]
    tail = (1 - confidence) / 2
    records = []
    for contrast in protocol["contrasts"]:
        candidate, reference = [names.index(contrast[key]) for key in ["candidate", "reference"]]
        if point[reference] <= 0 or (draws[:, reference] <= 0).any():
            raise ValueError("Relative MAE reduction is undefined for a zero-MAE reference")
        delta = draws[:, candidate] - draws[:, reference]
        reduction = 100 * (1 - draws[:, candidate] / draws[:, reference])
        delta_low, delta_high = np.quantile(delta, [tail, 1 - tail], method="linear")
        relative_low, relative_high = np.quantile(reduction, [tail, 1 - tail], method="linear")
        records.append(
            {
                **contrast,
                "delta_mae": float(point[candidate] - point[reference]),
                "delta_mae_low": float(delta_low),
                "delta_mae_high": float(delta_high),
                "relative_reduction_pct": float(100 * (1 - point[candidate] / point[reference])),
                "relative_reduction_pct_low": float(relative_low),
                "relative_reduction_pct_high": float(relative_high),
            }
        )
    return records


def run_uncertainty(
    config: dict, root: Path = Path("."), protocol_path: Path = Path("configs/uncertainty.toml")
) -> dict:
    path = protocol_path if protocol_path.is_absolute() else root / protocol_path
    with path.open("rb") as stream:
        protocol = tomllib.load(stream)
    study = protocol["study"]
    if study["method"] != "fold-stratified-circular-day-blocks":
        raise ValueError("Unsupported uncertainty method")
    blocks = [study["primary_block_days"], *study["sensitivity_block_days"]]
    if len(set(blocks)) != len(blocks) or not 0 < study["confidence_level"] < 1:
        raise ValueError("Block lengths must be unique and confidence level between zero and one")
    if type(study["replicates"]) is not int or study["replicates"] < 2:
        raise ValueError("At least two bootstrap replicates are required")
    if type(study["random_seed"]) is not int or study["random_seed"] < 0:
        raise ValueError("Random seed must be a nonnegative integer")
    directory = root / "reports/backtests" / study["backtest_id"]
    paths = [directory / "metrics.json", directory / "daily_mae.csv"]
    expected_hashes = [study["backtest_metrics_sha256"], study["daily_mae_sha256"]]
    for source, expected in zip(paths, expected_hashes, strict=True):
        if sha256(source) != expected:
            raise ValueError(f"Uncertainty input hash mismatch: {source.name}")
    backtest = json.loads(paths[0].read_text())
    if backtest["backtest_id"] != study["backtest_id"]:
        raise ValueError("Backtest identifier does not match the protocol")
    names, folds = validate_daily_errors(
        pd.read_csv(paths[1]), backtest, config["split"]["test_start"]
    )
    contrasts = [(c["candidate"], c["reference"]) for c in protocol["contrasts"]]
    if (
        not contrasts
        or len(contrasts) != len(set(contrasts))
        or any(c == r or c not in names or r not in names for c, r in contrasts)
    ):
        raise ValueError("Contrasts must contain unique pairs of different recorded models")
    point = np.array([backtest["pooled_metrics"][name]["mae"] for name in names])
    results, draws = [], {}
    for block in blocks:
        sample = bootstrap_mae(folds, block, study["replicates"], study["random_seed"])
        draws[f"block_{block}_mae"] = sample
        results.extend(
            {
                "block_days": block,
                "role": "primary" if block == study["primary_block_days"] else "sensitivity",
                "confidence_level": study["confidence_level"],
                **result,
            }
            for result in compare_draws(sample, point, names, protocol)
        )
    for source, expected in zip(paths, expected_hashes, strict=True):
        if sha256(source) != expected:
            raise ValueError("Input changed during resampling")
    identifier = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:6]
    output = root / "reports/uncertainty" / identifier
    output.mkdir(parents=True, exist_ok=False)
    artifact = root / "artifacts/uncertainty" / identifier
    artifact.mkdir(parents=True, exist_ok=False)
    np.savez_compressed(artifact / "draws.npz", model_names=np.array(names), **draws)
    pd.DataFrame(results).to_csv(output / "comparison.csv", index=False)
    record = {
        "uncertainty_id": identifier,
        "created_at": datetime.now(UTC).isoformat(),
        "protocol": protocol,
        "protocol_sha256": sha256(path),
        "input_sha256": {str(p.relative_to(root)): sha256(p) for p in paths},
        "source_hashes": {
            str(p.relative_to(root)): sha256(p) for p in sorted((root / "src").rglob("*.py"))
        },
        "lockfile_sha256": sha256(root / "uv.lock"),
        "draws_sha256": sha256(artifact / "draws.npz"),
        "git_revision": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False
        ).stdout.strip(),
        "git_worktree_dirty": bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            ).stdout.strip()
        ),
        "validation_days": sum(len(weights) for weights, _ in folds),
        "validation_rows": backtest["validation_rows"],
        "comparisons": results,
        "models_refitted": 0,
        "serving_model_changed": False,
        "test_metrics": None,
        "interpretation": "Marginal percentile intervals conditional on fixed development models "
        "and monthly composition; not future-performance guarantees or prediction intervals.",
    }
    write_json(output / "metrics.json", record)
    write_json(root / "reports/latest_uncertainty.json", record)
    print(f"Completed uncertainty analysis {identifier}", flush=True)
    print(pd.DataFrame(results).to_string(index=False), flush=True)
    return record
