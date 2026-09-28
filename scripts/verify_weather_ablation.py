"""Independently reconcile saved development forecasts without fitting any models."""

import argparse
import json
import tomllib
from pathlib import Path

import numpy as np
import pandas as pd

from nyc_mobility.config import TIMEZONE, write_json
from nyc_mobility.data.download import sha256
from nyc_mobility.evaluation.controls import CONTROL_NAMES, checked_hash, load_control
from nyc_mobility.evaluation.splits import expanding_folds, local_boundary, require_complete_window

METRICS = ["mae", "rmse", "r2", "smape_pct"]
CANDIDATES = ["weather_3h", "weather_6h"]
CONTRASTS = [
    ("weather_3h", "hist_gradient_boosting"),
    ("weather_6h", "hist_gradient_boosting"),
    ("weather_6h", "weather_3h"),
]


def independent_scores(actual, predicted) -> dict:
    """Use direct arithmetic, separately from the study's sklearn metric helper."""
    actual, predicted = np.asarray(actual, dtype=float), np.asarray(predicted, dtype=float)
    if (
        actual.ndim != 1
        or actual.shape != predicted.shape
        or not actual.size
        or not np.isfinite(actual).all()
        or not np.isfinite(predicted).all()
        or (actual < 0).any()
        or (predicted < 0).any()
    ):
        raise ValueError("Invalid saved targets or predictions")
    error = actual - predicted
    centered_sum = np.sum((actual - actual.mean()) ** 2)
    denominator = np.abs(actual) + np.abs(predicted)
    return {
        "mae": float(np.abs(error).mean()),
        "rmse": float(np.sqrt(np.mean(error**2))),
        "r2": float(1 - np.sum(error**2) / centered_sum) if centered_sum else None,
        "smape_pct": float(
            np.divide(
                200 * np.abs(error),
                denominator,
                out=np.zeros_like(actual),
                where=denominator != 0,
            ).mean()
        ),
    }


def check_value(actual, saved, label: str) -> float:
    if actual is None:
        if not pd.isna(saved):
            raise ValueError(f"Unexpected non-null metric: {label}")
        return 0.0
    if pd.isna(saved) or not np.isclose(actual, saved, rtol=1e-12, atol=1e-12):
        raise ValueError(f"Saved value does not reconcile: {label}: {actual} != {saved}")
    return abs(actual - saved)


def require_keys(table: pd.DataFrame, expected: set, label: str) -> None:
    if not table.index.is_unique or set(table.index) != expected:
        raise ValueError(f"Missing, duplicate or extra {label} rows")


def verify_fit_ledger(record: dict, fold_names: set[str]) -> dict:
    """Reject replacement fits or unfinished attempts even when summary counts look valid."""
    expected = {(fold, model) for fold in fold_names for model in CANDIDATES}
    attempts = record.get("fit_attempts")
    if (
        record.get("status") != "completed"
        or type(record.get("fits_attempted")) is not int
        or type(record.get("models_fitted")) is not int
        or record["fits_attempted"] != len(expected)
        or record["models_fitted"] != len(expected)
        or not isinstance(attempts, list)
        or len(attempts) != len(expected)
    ):
        raise ValueError("Fit ledger must contain exactly the completed frozen fit budget")
    durations = {}
    for attempt in attempts:
        if not isinstance(attempt, dict):
            raise ValueError("Invalid fit attempt")
        fold, model = attempt.get("fold"), attempt.get("model")
        duration = attempt.get("fit_and_predict_seconds")
        if (
            not isinstance(fold, str)
            or not isinstance(model, str)
            or (fold, model) not in expected
            or (fold, model) in durations
            or attempt.get("status") != "completed"
            or attempt.get("fit_completed") is not True
            or type(duration) not in (int, float)
            or not np.isfinite(duration)
            or duration < 0
        ):
            raise ValueError("Fit ledger contains a duplicate, extra or incomplete attempt")
        durations[(fold, model)] = duration
    return durations


def verify_output_hashes(directory: Path, recorded: dict) -> None:
    """Check every declared report table, including the no-fit preflight evidence."""
    required = {
        "pooled_metrics.csv",
        "fold_metrics.csv",
        "slice_metrics.csv",
        "daily_mae.csv",
        "comparison.csv",
        "preflight.csv",
    }
    expected = {directory.resolve() / name for name in required}
    if len(recorded) != len(expected) or {Path(name).resolve() for name in recorded} != expected:
        raise ValueError("Report output manifest must cover exactly the six published tables")
    for name, expected_hash in recorded.items():
        checked_hash(Path(name), expected_hash)


def verify(directory: Path) -> dict:
    record = json.loads((directory / "metrics.json").read_text())
    protocol = record["protocol"]
    study = protocol["study"]
    frozen = Path("configs/weather_ablation.toml")
    if protocol != tomllib.loads(frozen.read_text()):
        raise ValueError("Recorded weather protocol differs from the frozen specification")
    if (
        study["weather_delays_hours"] != [3, 6]
        or study["fit_budget"] != 6
        or record["models_fitted"] != 6
        or record["control_models_refitted"] != 0
        or record["serving_model_changed"] is not False
        or record["test_metrics"] is not None
    ):
        raise ValueError("Study exceeds the fixed fit budget or serving/test scope")
    for group in ["input_sha256", "source_hashes", "preserved_sha256"]:
        for name, expected in record[group].items():
            checked_hash(Path(name), expected)
    verify_output_hashes(directory, record["outputs_sha256"])
    checked_hash(frozen, record["protocol_sha256"])
    control_record, controls = load_control(protocol, Path("."), feature_set="temporal-latency-v1")
    control_details = {d["name"]: d for d in control_record["folds"] if d["delay_hours"] == 0}
    expected_folds = expanding_folds(
        study["train_start"], study["validation_boundaries"], study["sealed_test_start"]
    )
    details = {fold["name"]: fold for fold in record["folds"]}
    fold_names = {fold.name for fold in expected_folds}
    if (
        len(record["folds"]) != 3
        or set(details) != fold_names
        or set(controls) != fold_names
        or set(record["prediction_sha256"]) != fold_names
    ):
        raise ValueError("Saved folds differ from the three declared development windows")
    fit_durations = verify_fit_ledger(record, fold_names)
    artifact_dir = Path("artifacts/weather_ablation") / record["weather_ablation_id"]
    names = CONTROL_NAMES + CANDIDATES
    frames = []
    for fold in expected_folds:
        detail, original = details[fold.name], control_details[fold.name]
        for key in [
            "train_start",
            "effective_train_start",
            "effective_train_end_exclusive",
            "training_max_target",
            "validation_start",
            "validation_end",
            "validation_max_target",
            "train_rows",
            "validation_rows",
            "training_targets_sha256",
            "sparse_zone_ids",
        ]:
            if detail[key] != original[key]:
                raise ValueError(f"Control training/validation identity changed: {fold.name}/{key}")
        if set(detail["fit_and_predict_seconds"]) != set(CANDIDATES):
            raise ValueError("Recorded fit ledger does not match the two weather candidates")
        for candidate in CANDIDATES:
            check_value(
                fit_durations[(fold.name, candidate)],
                detail["fit_and_predict_seconds"][candidate],
                f"fit ledger timing/{fold.name}/{candidate}",
            )
        path = artifact_dir / f"{fold.name}.parquet"
        checked_hash(path, record["prediction_sha256"][fold.name])
        frame, saved = pd.read_parquet(path), controls[fold.name]
        if set(frame) != set(saved) | set(CANDIDATES):
            raise ValueError("Saved prediction columns differ from the fixed candidate set")
        pd.testing.assert_frame_equal(frame[list(saved)], saved)
        require_complete_window(
            frame, sorted(saved.zone_id.unique()), fold.validation_start, fold.validation_end
        )
        if not frame.fold.eq(fold.name).all() or len(frame) != detail["validation_rows"]:
            raise ValueError("Incorrect saved fold identity or row count")
        frames.append(frame)
    combined = pd.concat(frames, ignore_index=True)
    if combined.hour.max() >= local_boundary(study["sealed_test_start"]):
        raise ValueError("Saved predictions include sealed test targets")
    if combined.duplicated(["zone_id", "hour"]).any() or len(combined) != record["validation_rows"]:
        raise ValueError("Invalid saved target coverage")

    pooled = pd.read_csv(directory / "pooled_metrics.csv").set_index("model")
    folds = pd.read_csv(directory / "fold_metrics.csv").set_index(["fold", "model"])
    require_keys(pooled, set(names), "pooled metric")
    require_keys(folds, {(fold, name) for fold in fold_names for name in names}, "fold metric")
    if set(record["pooled_metrics"]) != set(names):
        raise ValueError("Pooled record contains different candidate names")
    scores, discrepancies = {}, []
    for scope, frame in [("pooled", combined), *list(combined.groupby("fold"))]:
        scores[scope] = {}
        stored = record["pooled_metrics"] if scope == "pooled" else details[scope]["metrics"]
        if set(stored) != set(names):
            raise ValueError("Fold record contains different candidate names")
        for name in names:
            values = independent_scores(frame.demand, frame[name])
            scores[scope][name] = values
            row = pooled.loc[name] if scope == "pooled" else folds.loc[(scope, name)]
            for key, value in values.items():
                for source in [row, stored[name]]:
                    discrepancies.append(check_value(value, source[key], f"{scope}/{name}/{key}"))

    days = pd.read_csv(directory / "daily_mae.csv")
    indexed = days.set_index(["fold", "date_nyc", "model"], verify_integrity=True)
    local_dates = combined.hour.dt.tz_convert(TIMEZONE).dt.strftime("%Y-%m-%d")
    day_keys, day_counts = set(), {}
    zones_count = combined.zone_id.nunique()
    for (fold, day), frame in combined.groupby(["fold", local_dates]):
        start = local_boundary(day)
        tomorrow = (pd.Timestamp(day) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        hours = int((local_boundary(tomorrow) - start) / pd.Timedelta(hours=1))
        if len(frame) != hours * zones_count:
            raise ValueError("Local daily coverage differs from timezone-aware calendar hours")
        day_counts[day] = len(frame)
        for name in names:
            key = (fold, day, name)
            day_keys.add(key)
            row = indexed.loc[key]
            if row.rows != len(frame):
                raise ValueError("Saved daily row counts differ")
            absolute_errors = np.abs(frame.demand - frame[name])
            check_value(float(absolute_errors.mean()), row.mae, str(key))
            check_value(
                float(absolute_errors.sum()), row.absolute_error_sum, f"daily absolute sum/{key}"
            )
    require_keys(indexed, day_keys, "daily metric")
    for name in names:
        selected = days.loc[days.model.eq(name)]
        check_value(
            scores["pooled"][name]["mae"],
            np.average(selected.mae, weights=selected.rows),
            f"daily weighted pooled MAE/{name}",
        )

    slices = pd.read_csv(directory / "slice_metrics.csv", dtype={"value": str}).set_index(
        ["fold", "model", "dimension", "value"], verify_integrity=True
    )
    slice_keys = set()
    slice_discrepancies = []
    for fold, frame in combined.groupby("fold"):
        for dimension in [
            "borough",
            "local_hour",
            "weekend",
            "rush_hour",
            "zone_cohort",
            "target_cohort",
        ]:
            for value, subset in frame.groupby(dimension):
                for name in names:
                    key = (fold, name, dimension, str(value))
                    slice_keys.add(key)
                    row = slices.loc[key]
                    if row.rows != len(subset):
                        raise ValueError("Saved slice row count differs")
                    values = {
                        **independent_scores(subset.demand, subset[name]),
                        "mean_prediction": float(subset[name].mean()),
                        "positive_prediction_fraction": float(subset[name].gt(0).mean()),
                    }
                    for metric, actual in values.items():
                        slice_discrepancies.append(check_value(actual, row[metric], str(key)))
    require_keys(slices, slice_keys, "slice metric")

    comparisons = pd.read_csv(directory / "comparison.csv").set_index(
        ["scope", "candidate", "reference"], verify_integrity=True
    )
    comparison_keys = {(scope, a, b) for scope in scores for a, b in CONTRASTS}
    require_keys(comparisons, comparison_keys, "comparison")
    for scope, candidate, reference in comparison_keys:
        actual, base = scores[scope][candidate]["mae"], scores[scope][reference]["mae"]
        row = comparisons.loc[(scope, candidate, reference)]
        for key, value in {
            "mae": actual,
            "reference_mae": base,
            "delta_mae": actual - base,
            "relative_reduction_pct": 100 * (1 - actual / base) if base else None,
        }.items():
            check_value(value, row[key], f"comparison/{scope}/{candidate}/{reference}/{key}")
    unchanged = {
        **record["preserved_sha256"],
        **{
            name: record["input_sha256"][name]
            for name in ["data/processed/hourly_demand.parquet", "uv.lock"]
        },
    }
    verification = {
        "weather_ablation_id": record["weather_ablation_id"],
        "unchanged_files_sha256": unchanged,
        "input_source_control_hashes_match": True,
        "control_forecasts_targets_and_cohorts_identical": True,
        "prediction_hashes_match": True,
        "report_output_hashes_match": True,
        "six_completed_fit_attempts_verified": True,
        "recorded_weather_fits": record["models_fitted"],
        "recorded_control_refits": record["control_models_refitted"],
        "validation_rows": len(combined),
        "validation_max_target": combined.hour.max().isoformat(),
        "daily_rows_independently_checked": len(day_keys),
        "local_calendar_dates": len(day_counts),
        "daily_target_rows": day_counts,
        "metrics_independently_checked": METRICS,
        "pooled_and_fold_metrics_max_absolute_discrepancy": max(discrepancies),
        "slice_rows_independently_checked": len(slice_keys),
        "slice_metrics_max_absolute_discrepancy": max(slice_discrepancies),
        "comparison_rows_independently_checked": len(comparison_keys),
        "verification_models_fitted": 0,
        "test_metrics": None,
        "verification_script_sha256": sha256(Path(__file__)),
    }
    write_json(directory / "verification.json", verification)
    print(
        json.dumps(
            {
                k: v
                for k, v in verification.items()
                if k not in {"unchanged_files_sha256", "daily_target_rows"}
            },
            indent=2,
        )
    )
    return verification


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report_directory", type=Path)
    args = parser.parse_args()
    verify(args.report_directory)
