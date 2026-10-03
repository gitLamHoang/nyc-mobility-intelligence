"""Verify saved weather intervals and reproduce from published summaries in isolation."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

import numpy as np
import pandas as pd

from nyc_mobility.config import write_json
from nyc_mobility.data.download import sha256

CONTRASTS = [
    ("weather_3h", "hist_gradient_boosting"),
    ("weather_6h", "hist_gradient_boosting"),
]
MODEL_NAMES = [
    "latest_available",
    "previous_day_24h",
    "previous_week_168h",
    "zone_hour_average",
    "rolling_mean_24h",
    "hist_gradient_boosting",
    "weather_3h",
    "weather_6h",
]


def linear_percentiles(values: np.ndarray, probabilities: list[float]) -> np.ndarray:
    """Interpolate order statistics directly, independently of NumPy's quantile API."""
    ordered = np.sort(np.asarray(values, dtype=float))
    if ordered.ndim != 1 or not len(ordered) or not np.isfinite(ordered).all():
        raise ValueError("Percentiles require nonempty finite one-dimensional draws")
    probabilities = np.asarray(probabilities, dtype=float)
    if not np.isfinite(probabilities).all() or ((probabilities < 0) | (probabilities > 1)).any():
        raise ValueError("Percentile probabilities must be between zero and one")
    positions = (len(ordered) - 1) * probabilities
    lower = np.floor(positions).astype(int)
    upper = np.ceil(positions).astype(int)
    return ordered[lower] + (positions - lower) * (ordered[upper] - ordered[lower])


def verify_daily_points(daily: pd.DataFrame, study: dict) -> float:
    """Independently reconcile complete local-day totals with saved fold/pooled points."""
    assert set(daily) == {"fold", "date_nyc", "model", "rows", "mae", "absolute_error_sum"}
    assert len(daily) == 89 * 8 and not daily.isna().any().any()
    assert not daily.duplicated(["fold", "date_nyc", "model"]).any()
    assert set(daily.model) == set(MODEL_NAMES)
    assert list(study["pooled_metrics"]) == MODEL_NAMES
    assert study["validation_rows"] == 559370 and study["test_metrics"] is None
    assert len(study["folds"]) == 3
    assert [f["name"] for f in study["folds"]] == ["fold_1", "fold_2", "fold_3"]
    assert set(daily.fold) == {"fold_1", "fold_2", "fold_3"}
    numeric = daily[["rows", "mae", "absolute_error_sum"]].to_numpy()
    assert np.isfinite(numeric).all() and (numeric >= 0).all()
    assert np.allclose(daily.absolute_error_sum, daily.rows * daily.mae, rtol=1e-12, atol=1e-9)
    largest_discrepancy = 0.0
    for month, fold in zip([2, 3, 4], study["folds"], strict=True):
        start = pd.Timestamp(f"2026-{month:02d}-01", tz="America/New_York")
        end = pd.Timestamp(f"2026-{month + 1:02d}-01", tz="America/New_York")
        assert pd.Timestamp(fold["validation_start"]) == start
        assert pd.Timestamp(fold["validation_end"]) == end
        days = pd.date_range(start, end, freq="D")
        names = days[:-1].strftime("%Y-%m-%d").tolist()
        weights = (np.diff(days.asi8) / (3600 * 1e9) * 262).astype(int)
        frame = daily.loc[daily.fold == fold["name"]]
        rows = frame.pivot(index="date_nyc", columns="model", values="rows")
        assert set(rows.index) == set(names)
        assert (rows.reindex(index=names, columns=MODEL_NAMES).to_numpy() == weights[:, None]).all()
        assert int(weights.sum()) == fold["validation_rows"]
        for model in MODEL_NAMES:
            values = frame.loc[frame.model == model]
            point = values.absolute_error_sum.sum() / values.rows.sum()
            expected = fold["metrics"][model]["mae"]
            largest_discrepancy = max(largest_discrepancy, abs(point - expected))
            assert np.isclose(point, expected, rtol=1e-12, atol=1e-14)
    for model in MODEL_NAMES:
        values = daily.loc[daily.model == model]
        assert values.rows.sum() == 559370
        point = values.absolute_error_sum.sum() / values.rows.sum()
        expected = study["pooled_metrics"][model]["mae"]
        largest_discrepancy = max(largest_discrepancy, abs(point - expected))
        assert np.isclose(point, expected, rtol=1e-12, atol=1e-14)
    return float(largest_discrepancy)


def verify(directory: Path, preservation_record: Path | None = None) -> dict:
    root = Path.cwd()
    record = json.loads((directory / "metrics.json").read_text())
    protocol = record["protocol"]
    assert protocol == tomllib.loads((root / "configs/weather_uncertainty.toml").read_text())
    specification = protocol["study"]
    fixed = {
        "id": "paired-weather-day-block-v1",
        "method": "fold-stratified-circular-day-blocks",
        "primary_weather_delay_hours": 3,
        "primary_block_days": 7,
        "sensitivity_block_days": [1, 14],
        "replicates": 10000,
        "random_seed": 42,
        "confidence_level": 0.95,
        "family_confidence_level": 0.95,
        "family_size": 2,
        "family_method": "bonferroni",
        "family_metric": "delta_mae",
    }
    assert {k: specification[k] for k in fixed} == fixed
    assert sha256(root / "configs/weather_uncertainty.toml") == record["protocol_sha256"]
    assert (
        sha256(root / "docs/WEATHER_UNCERTAINTY_PROTOCOL.md") == record["protocol_document_sha256"]
    )
    assert sha256(root / "uv.lock") == record["lockfile_sha256"]
    assert record["source_hashes"] == {
        str(p.relative_to(root)): sha256(p) for p in sorted((root / "src").rglob("*.py"))
    }
    for name, digest in {**record["input_sha256"], **record["source_hashes"]}.items():
        assert sha256(root / name) == digest, f"Changed evidence/source: {name}"
    source = root / "reports/weather_ablation" / protocol["study"]["weather_ablation_id"]
    for name, digest in {
        "metrics.json": specification["metrics_sha256"],
        "daily_mae.csv": specification["daily_mae_sha256"],
    }.items():
        assert sha256(source / name) == digest
        assert record["input_sha256"][str((source / name).relative_to(root))] == digest
    study = json.loads((source / "metrics.json").read_text())
    assert study["weather_ablation_id"] == specification["weather_ablation_id"]
    daily_discrepancy = verify_daily_points(pd.read_csv(source / "daily_mae.csv"), study)
    artifact = root / "artifacts/weather_uncertainty" / record["uncertainty_id"] / "draws.npz"
    assert sha256(artifact) == record["draws_sha256"]
    contrasts = [(c["candidate"], c["reference"]) for c in protocol["contrasts"]]
    assert contrasts == CONTRASTS
    comparisons = record["comparisons"]
    expected_keys = {(c, r, block) for c, r in contrasts for block in [7, 1, 14]}
    assert len(comparisons) == 6
    assert {(r["candidate"], r["reference"], r["block_days"]) for r in comparisons} == expected_keys
    assert record["models_refitted"] == record["target_tables_read"] == 0
    assert record["test_metrics"] is None and not record["serving_model_changed"]
    assert record["validation_days"] == 89 and record["validation_rows"] == 559370
    assert record["quantile_method"] == "linear"
    saved_csv = pd.read_csv(directory / "comparison.csv")
    assert sha256(directory / "comparison.csv") == record["comparison_sha256"]
    pd.testing.assert_frame_equal(saved_csv, pd.DataFrame(comparisons), rtol=1e-12, atol=1e-15)
    largest_discrepancy = 0.0
    with np.load(artifact, allow_pickle=False) as draws:
        names = draws["model_names"].tolist()
        assert names == record["model_names"] == MODEL_NAMES
        assert set(draws.files) == {"model_names", "block_7_mae", "block_1_mae", "block_14_mae"}
        for row in comparisons:
            block = row["block_days"]
            values = draws[f"block_{block}_mae"]
            assert values.shape == (10000, len(names))
            assert np.isfinite(values).all() and (values >= 0).all()
            c, r = (names.index(row[k]) for k in ["candidate", "reference"])
            assert (values[:, r] > 0).all()
            delta = values[:, c] - values[:, r]
            relative = 100 * (1 - values[:, c] / values[:, r])
            marginal = linear_percentiles(delta, [0.025, 0.975])
            adjusted = linear_percentiles(delta, [0.0125, 0.9875])
            relative_ci = linear_percentiles(relative, [0.025, 0.975])
            candidate = study["pooled_metrics"][row["candidate"]]["mae"]
            reference = study["pooled_metrics"][row["reference"]]["mae"]
            expected = {
                "delta_mae": candidate - reference,
                "delta_mae_low": marginal[0],
                "delta_mae_high": marginal[1],
                "delta_mae_family_low": adjusted[0],
                "delta_mae_family_high": adjusted[1],
                "relative_reduction_pct": 100 * (1 - candidate / reference),
                "relative_reduction_pct_low": relative_ci[0],
                "relative_reduction_pct_high": relative_ci[1],
            }
            assert row["role"] == ("primary" if block == 7 else "sensitivity")
            assert row["weather_role"] == (
                "primary" if row["candidate"] == "weather_3h" else "sensitivity"
            )
            assert row["family_size"] == 2 and row["family_metric"] == "delta_mae"
            assert row["family_method"] == "bonferroni"
            assert row["confidence_level"] == row["family_confidence_level"] == 0.95
            assert np.isclose(row["per_contrast_confidence_level"], 0.975)
            for key, value in expected.items():
                discrepancy = abs(value - row[key])
                largest_discrepancy = max(largest_discrepancy, float(discrepancy))
                assert np.isclose(value, row[key], rtol=1e-12, atol=1e-14), key
        with tempfile.TemporaryDirectory(prefix="weather-summary-reproduction-") as temporary:
            isolated = Path(temporary)
            shutil.copytree(
                root / "src", isolated / "src", ignore=shutil.ignore_patterns("__pycache__")
            )
            for name in [
                "configs/default.toml",
                "configs/weather_uncertainty.toml",
                "docs/WEATHER_UNCERTAINTY_PROTOCOL.md",
                "uv.lock",
                *record["input_sha256"],
            ]:
                target = isolated / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(root / name, target)
            assert not (isolated / "data").exists() and not (isolated / "artifacts").exists()
            subprocess.run(
                [sys.executable, "-m", "nyc_mobility.cli", "weather-uncertainty"],
                cwd=isolated,
                env={**os.environ, "PYTHONPATH": str(isolated / "src")},
                capture_output=True,
                text=True,
                check=True,
            )
            repeated = json.loads(
                (isolated / "reports/latest_weather_uncertainty.json").read_text()
            )
            for key in [
                "comparisons",
                "protocol_sha256",
                "protocol_document_sha256",
                "comparison_sha256",
                "input_sha256",
                "source_hashes",
                "lockfile_sha256",
                "validation_days",
                "validation_rows",
                "model_names",
            ]:
                assert repeated[key] == record[key], key
            repeated_artifact = (
                isolated
                / "artifacts/weather_uncertainty"
                / repeated["uncertainty_id"]
                / "draws.npz"
            )
            with np.load(repeated_artifact, allow_pickle=False) as second:
                assert set(draws.files) == set(second.files)
                for key in draws.files:
                    np.testing.assert_array_equal(draws[key], second[key])
            repeated_csv = (
                isolated
                / "reports/weather_uncertainty"
                / repeated["uncertainty_id"]
                / "comparison.csv"
            )
            assert repeated_csv.read_bytes() == (directory / "comparison.csv").read_bytes()
    preserved = json.loads(preservation_record.read_text()) if preservation_record else {}
    for name, digest in preserved.items():
        assert sha256(root / name) == digest, f"Existing artifact changed: {name}"
    evidence = {
        "uncertainty_id": record["uncertainty_id"],
        "input_protocol_source_lock_hashes_match": True,
        "comparisons_independently_checked": len(comparisons),
        "daily_summary_rows_independently_checked": 89 * 8,
        "maximum_daily_mae_discrepancy": daily_discrepancy,
        "maximum_percentile_discrepancy": largest_discrepancy,
        "isolated_summary_reproduction": True,
        "isolated_comparison_csv_identical": True,
        "isolated_draw_arrays_identical": True,
        "unchanged_files_sha256": preserved,
        "verification_models_fitted": 0,
        "test_metrics": None,
        "verification_script_sha256": sha256(Path(__file__)),
    }
    target = directory / "verification.json"
    if target.exists():
        raise FileExistsError("Preserve the existing verification report; use a new run directory")
    write_json(target, evidence)
    print(json.dumps(evidence, indent=2))
    return evidence


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report_directory", type=Path)
    parser.add_argument("--preservation-record", type=Path)
    args = parser.parse_args()
    verify(args.report_directory, args.preservation_record)
