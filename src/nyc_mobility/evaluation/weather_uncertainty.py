"""Frozen paired weather uncertainty from daily summaries, without targets or fitting."""

import json
import re
import subprocess
import tomllib
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd

from nyc_mobility.config import write_json
from nyc_mobility.data.download import sha256
from nyc_mobility.evaluation.splits import local_boundary
from nyc_mobility.evaluation.uncertainty import (
    bootstrap_mae,
    family_comparisons,
    validate_daily_errors,
)

CONTRASTS = [
    {"candidate": "weather_3h", "reference": "hist_gradient_boosting"},
    {"candidate": "weather_6h", "reference": "hist_gradient_boosting"},
]
MODELS = {
    "latest_available",
    "previous_day_24h",
    "previous_week_168h",
    "zone_hour_average",
    "rolling_mean_24h",
    "hist_gradient_boosting",
    "weather_3h",
    "weather_6h",
}
FROZEN_SETTINGS = {
    "id": "paired-weather-day-block-v1",
    "method": "fold-stratified-circular-day-blocks",
    "primary_weather_delay_hours": 3,
    "primary_block_days": 7,
    "sensitivity_block_days": [1, 14],
    "replicates": 10000,
    "confidence_level": 0.95,
    "random_seed": 42,
    "family_method": "bonferroni",
    "family_metric": "delta_mae",
    "family_size": 2,
    "family_confidence_level": 0.95,
}
BOUNDARIES = ["2026-02-01", "2026-03-01", "2026-04-01", "2026-05-01"]
DAILY_COLUMNS = ["fold", "date_nyc", "model", "rows", "mae"]


def validate_protocol(protocol: dict) -> list[int]:
    """Reject deviations from the committed two-contrast resampling plan."""
    study = protocol.get("study", {})
    pinned = {"weather_ablation_id", "metrics_sha256", "daily_mae_sha256"}
    if set(protocol) != {"study", "contrasts"} or set(study) != set(FROZEN_SETTINGS) | pinned:
        raise ValueError("Weather uncertainty requires the complete frozen protocol schema")
    for key, expected in FROZEN_SETTINGS.items():
        actual = study[key]
        if type(actual) is not type(expected) or actual != expected:
            raise ValueError(f"Frozen weather uncertainty setting changed: {key}")
        if isinstance(expected, list) and any(type(value) is not int for value in actual):
            raise ValueError(f"Frozen weather uncertainty setting changed: {key}")
    if protocol["contrasts"] != CONTRASTS:
        raise ValueError("The family must contain exactly the two frozen weather MAE contrasts")
    if not isinstance(study["weather_ablation_id"], str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_-]*", study["weather_ablation_id"]
    ):
        raise ValueError("Weather study identifier must be a single safe path component")
    for key in ["metrics_sha256", "daily_mae_sha256"]:
        if not isinstance(study[key], str) or not re.fullmatch(r"[0-9a-f]{64}", study[key]):
            raise ValueError(f"Invalid pinned input hash: {key}")
    return [study["primary_block_days"], *study["sensitivity_block_days"]]


def validate_weather_errors(daily: pd.DataFrame, record: dict, sealed_test_start: str):
    """Validate the fixed eight-model, three-fold grid and actual error totals."""
    if set(daily) != {*DAILY_COLUMNS, "absolute_error_sum"}:
        raise ValueError("Weather daily errors require the complete absolute-error schema")
    totals = daily["absolute_error_sum"].to_numpy(dtype=float)
    expected = daily["rows"].to_numpy(dtype=float) * daily["mae"].to_numpy(dtype=float)
    if (
        not np.isfinite(totals).all()
        or (totals < 0).any()
        or not np.allclose(totals, expected, rtol=1e-10, atol=1e-12)
    ):
        raise ValueError("Daily absolute-error totals must be finite and equal rows times MAE")
    study = record["protocol"]["study"]
    if (
        sealed_test_start != BOUNDARIES[-1]
        or study["validation_boundaries"] != BOUNDARIES
        or study["primary_weather_delay_hours"] != 3
        or study["weather_delays_hours"] != [3, 6]
        or record["status"] != "completed"
        or record["models_fitted"] != 6
        or record["fits_attempted"] != 6
        or record["control_models_refitted"] != 0
        or record["serving_model_changed"] is not False
        or record["historical_weather_publication_verified"] is not False
    ):
        raise ValueError("Weather source must be the completed frozen development study")
    folds = record["folds"]
    if (
        set(record["pooled_metrics"]) != MODELS
        or len(folds) != 3
        or record["validation_rows"] != 559370
    ):
        raise ValueError("Weather errors require all eight models and three complete folds")
    for index, fold in enumerate(folds):
        if (
            fold["name"] != f"fold_{index + 1}"
            or pd.Timestamp(fold["validation_start"]) != local_boundary(BOUNDARIES[index])
            or pd.Timestamp(fold["validation_end"]) != local_boundary(BOUNDARIES[index + 1])
            or set(fold["metrics"]) != MODELS
        ):
            raise ValueError("Weather fold dates/models differ from the frozen study")
    names, arrays = validate_daily_errors(daily[DAILY_COLUMNS], record, sealed_test_start)
    if sum(len(weights) for weights, _ in arrays) != 89:
        raise ValueError("Weather uncertainty requires all 89 development dates")
    return names, arrays


def _source_hashes(root: Path) -> dict:
    return {str(p.relative_to(root)): sha256(p) for p in sorted((root / "src").rglob("*.py"))}


def run_weather_uncertainty(
    config: dict,
    root: Path = Path("."),
    protocol_path: Path = Path("configs/weather_uncertainty.toml"),
) -> dict:
    """Resample only pinned daily summaries; reject mutations before publishing outputs."""
    path = protocol_path if protocol_path.is_absolute() else root / protocol_path
    document = root / "docs/WEATHER_UNCERTAINTY_PROTOCOL.md"
    protocol_hash, document_hash = sha256(path), sha256(document)
    source_hashes = _source_hashes(root)
    lock_hash = sha256(root / "uv.lock")
    protocol = tomllib.loads(path.read_text())
    blocks = validate_protocol(protocol)
    study = protocol["study"]
    source = root / "reports/weather_ablation" / study["weather_ablation_id"]
    paths = [source / "metrics.json", source / "daily_mae.csv"]
    hashes = [study["metrics_sha256"], study["daily_mae_sha256"]]
    for p, expected in zip(paths, hashes, strict=True):
        if sha256(p) != expected:
            raise ValueError(f"Uncertainty input hash mismatch: {p.name}")
    record = json.loads(paths[0].read_text())
    if record["weather_ablation_id"] != study["weather_ablation_id"]:
        raise ValueError("Weather source identifier differs from protocol")
    names, folds = validate_weather_errors(
        pd.read_csv(paths[1]), record, config["split"]["test_start"]
    )
    point = np.array([record["pooled_metrics"][name]["mae"] for name in names])
    results, draws = [], {}
    for block in blocks:
        sample = bootstrap_mae(folds, block, study["replicates"], study["random_seed"])
        draws[f"block_{block}_mae"] = sample
        results.extend(
            {
                "block_days": block,
                "role": "primary" if block == study["primary_block_days"] else "sensitivity",
                "confidence_level": study["confidence_level"],
                "weather_role": "primary" if result["candidate"] == "weather_3h" else "sensitivity",
                **result,
            }
            for result in family_comparisons(sample, point, names, protocol)
        )
    for p, expected in zip(
        [path, document, *paths], [protocol_hash, document_hash, *hashes], strict=True
    ):
        if sha256(p) != expected:
            raise ValueError("Protocol or input changed during resampling")
    if source_hashes != _source_hashes(root) or sha256(root / "uv.lock") != lock_hash:
        raise ValueError("Source or dependency lock changed during resampling")
    identifier = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:6]
    output = root / "reports/weather_uncertainty" / identifier
    artifact = root / "artifacts/weather_uncertainty" / identifier
    output.mkdir(parents=True, exist_ok=False)
    artifact.mkdir(parents=True, exist_ok=False)
    np.savez_compressed(artifact / "draws.npz", model_names=np.array(names), **draws)
    pd.DataFrame(results).to_csv(output / "comparison.csv", index=False)
    result = {
        "uncertainty_id": identifier,
        "created_at": datetime.now(UTC).isoformat(),
        "protocol": protocol,
        "protocol_sha256": protocol_hash,
        "protocol_document_sha256": document_hash,
        "input_sha256": dict(zip((str(p.relative_to(root)) for p in paths), hashes, strict=True)),
        "source_hashes": source_hashes,
        "lockfile_sha256": lock_hash,
        "draws_sha256": sha256(artifact / "draws.npz"),
        "comparison_sha256": sha256(output / "comparison.csv"),
        "versions": {name: version(name) for name in ["numpy", "pandas"]},
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
        "validation_rows": record["validation_rows"],
        "model_names": names,
        "comparisons": results,
        "quantile_method": "linear",
        "models_refitted": 0,
        "target_tables_read": 0,
        "serving_model_changed": False,
        "test_metrics": None,
        "historical_weather_publication_verified": False,
        "scope": "Fixed February–April weather development errors; three-hour weather is primary.",
        "interpretation": "Nominal Bonferroni family covers two absolute MAE differences per block "
        "setting, conditional on the bootstrap approximation, fixed models and weather policy. "
        "Relative intervals are marginal. No coverage across settings, the full prior model "
        "selection sequence or future periods is claimed. Historical weather publication and "
        "revision availability remain unverified; sparse/zero-target and RMSE harms remain.",
    }
    write_json(output / "metrics.json", result)
    write_json(root / "reports/latest_weather_uncertainty.json", result)
    print(f"Completed paired weather uncertainty {identifier}", flush=True)
    print(pd.DataFrame(results).to_string(index=False), flush=True)
    return result
