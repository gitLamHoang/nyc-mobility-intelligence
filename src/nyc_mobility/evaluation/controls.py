"""Shared integrity and coverage checks for immutable zero-delay latency controls."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from nyc_mobility.data.download import sha256
from nyc_mobility.evaluation.metrics import metrics
from nyc_mobility.evaluation.splits import require_complete_window
from nyc_mobility.features.temporal import FEATURES

CONTROL_NAMES = [
    "latest_available",
    "previous_day_24h",
    "previous_week_168h",
    "zone_hour_average",
    "rolling_mean_24h",
    "hist_gradient_boosting",
]


def checked_hash(path: Path, expected: str) -> None:
    if not path.is_file():
        raise ValueError(f"Required source artifact missing; restore the pinned control: {path}")
    if sha256(path) != expected:
        raise ValueError(f"Source SHA-256 mismatch: {path}")


def load_control(
    protocol: dict, root: Path, *, feature_set: str | None = None
) -> tuple[dict, dict]:
    spec = protocol["control"]
    report = root / "reports/latency" / spec["latency_id"] / "metrics.json"
    checked_hash(report, spec["metrics_sha256"])
    control = json.loads(report.read_text())
    if control["data_sha256"] != spec["data_sha256"] or control["features"] != FEATURES:
        raise ValueError("Control data or feature identity differs")
    feature_source = "src/nyc_mobility/features/temporal.py"
    checked_hash(root / feature_source, control["source_hashes"][feature_source])
    for key in [
        "train_start",
        "validation_boundaries",
        "sealed_test_start",
        "feature_set",
        "common_warmup_hours",
        "common_training_embargo_hours",
    ]:
        expected = feature_set if key == "feature_set" and feature_set else protocol["study"][key]
        if control["protocol"]["study"][key] != expected:
            raise ValueError(f"Control protocol differs: {key}")
    predictions = {}
    for fold, expected in spec["prediction_sha256"].items():
        path = root / "artifacts/latency" / spec["latency_id"] / f"delay_0_{fold}.parquet"
        checked_hash(path, expected)
        predictions[fold] = pd.read_parquet(path)
    return control, predictions


def matched_fold(features, fold, zones, study, saved, detail):
    """Verify shared training/validation coverage before allowing any candidate fit."""
    start = fold.train_start + pd.Timedelta(hours=study["common_warmup_hours"])
    end = fold.validation_start - pd.Timedelta(hours=study["common_training_embargo_hours"])
    train = features.loc[(features.hour >= start) & (features.hour < end)]
    valid = features.loc[
        (features.hour >= fold.validation_start) & (features.hour < fold.validation_end)
    ]
    require_complete_window(train, zones, start, end)
    require_complete_window(valid, zones, fold.validation_start, fold.validation_end)
    require_complete_window(saved, zones, fold.validation_start, fold.validation_end)
    signature = hashlib.sha256(
        pd.util.hash_pandas_object(train[["zone_id", "hour", "demand"]], index=False)
        .to_numpy()
        .tobytes()
    ).hexdigest()
    if signature != detail["training_targets_sha256"] or len(train) != detail["train_rows"]:
        raise ValueError("Training target signature differs from the control")
    for key, expected in {
        "effective_train_start": start,
        "effective_train_end_exclusive": end,
        "training_max_target": train.hour.max(),
        "validation_start": fold.validation_start,
        "validation_end": fold.validation_end,
    }.items():
        if pd.Timestamp(detail[key]) != expected:
            raise ValueError(f"Training or validation boundary differs: {key}")
    available_at = train.hour.max() + pd.Timedelta(hours=1 + study["observation_delay_hours"])
    if available_at > fold.validation_start:
        raise ValueError("Training labels unavailable at forecast origin")
    sparse_ids = (
        train.groupby("zone_id")
        .demand.mean()
        .loc[lambda values: values <= study["sparse_zone_mean_max"]]
        .index.tolist()
    )
    if sparse_ids != detail["sparse_zone_ids"]:
        raise ValueError("Training-defined sparse cohort differs")
    columns = ["zone_id", "hour", "demand", "borough", "local_hour", "weekend", "rush_hour"]
    expected = valid[columns].copy()
    expected["fold"] = fold.name
    expected["zone_cohort"] = np.where(valid.zone_id.isin(sparse_ids), "sparse", "dense")
    expected["target_cohort"] = np.where(valid.demand.eq(0), "zero", "positive")
    if not expected.reset_index(drop=True).equals(saved[list(expected)].reset_index(drop=True)):
        raise ValueError("Control validation keys, labels, order or cohorts differ")
    for name in CONTROL_NAMES:
        if not np.isfinite(saved[name]).all() or (saved[name] < 0).any():
            raise ValueError(f"Invalid control predictions: {name}")
        actual = metrics(saved.demand, saved[name])
        for metric, value in actual.items():
            reference = detail["metrics"][name][metric]
            if value is None:
                equal = reference is None
            else:
                equal = reference is not None and np.isclose(
                    value, reference, rtol=1e-12, atol=1e-12
                )
            if not equal:
                raise ValueError(f"Control metric mismatch: {name}/{metric}")
    return train, valid
