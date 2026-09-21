"""Fixed-protocol development backtesting, isolated from the serving model."""

import hashlib
import subprocess
import time
import tomllib
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd
from sklearn.base import clone

from nyc_mobility.config import TIMEZONE, write_json
from nyc_mobility.data.download import sha256
from nyc_mobility.data.prepare import load_zones
from nyc_mobility.evaluation.metrics import metrics
from nyc_mobility.evaluation.splits import (
    ForecastFold,
    expanding_folds,
    local_boundary,
    require_complete_window,
)
from nyc_mobility.features.temporal import FEATURES, make_features
from nyc_mobility.models.baselines import baseline_predictions
from nyc_mobility.models.train import estimators

WARMUP_HOURS = 168


def read_development_panel(path: Path, start: pd.Timestamp, stop: pd.Timestamp) -> pd.DataFrame:
    """Exclude test targets at the Parquet reader, before constructing any features."""
    return pd.read_parquet(path, filters=[("hour", ">=", start), ("hour", "<", stop)])


def study_estimators(model_config: dict, names: list[str]) -> dict:
    """Construct fresh independent estimators and preprocessing pipelines each fold."""
    candidates = estimators(model_config)
    control = candidates["hist_gradient_boosting"]
    for suffix, loss in [("poisson", "poisson"), ("absolute", "absolute_error")]:
        candidates[f"hist_gradient_boosting_{suffix}"] = clone(control).set_params(
            histgradientboostingregressor__loss=loss
        )
    if not names or len(names) != len(set(names)) or set(names) - set(candidates):
        raise ValueError("Protocol contains duplicate, absent or unsupported model names")
    return {name: candidates[name] for name in names}


def fit_fold(
    features: pd.DataFrame,
    fold: ForecastFold,
    zones: list[int],
    study: dict,
    model_config: dict,
    *,
    warmup_hours: int = WARMUP_HOURS,
    training_embargo_hours: int = 0,
) -> tuple[pd.DataFrame, dict, dict]:
    effective_start = fold.train_start + pd.Timedelta(hours=warmup_hours)
    effective_end = fold.validation_start - pd.Timedelta(hours=training_embargo_hours)
    train = features.loc[
        (features.hour >= effective_start) & (features.hour < effective_end)
    ].copy()
    valid = features.loc[
        (features.hour >= fold.validation_start) & (features.hour < fold.validation_end)
    ].copy()
    require_complete_window(train, zones, effective_start, effective_end)
    require_complete_window(valid, zones, fold.validation_start, fold.validation_end)
    sparse_ids = (
        train.groupby("zone_id")
        .demand.mean()
        .loc[lambda values: values <= study["sparse_zone_mean_max"]]
        .index.tolist()
    )
    result = valid[
        ["zone_id", "hour", "demand", "borough", "local_hour", "weekend", "rush_hour"]
    ].copy()
    result["fold"] = fold.name
    result["zone_cohort"] = np.where(result.zone_id.isin(sparse_ids), "sparse", "dense")
    result["target_cohort"] = np.where(result.demand.eq(0), "zero", "positive")
    predictions = baseline_predictions(train, valid)
    scores = {name: metrics(valid.demand, prediction) for name, prediction in predictions.items()}
    best_baseline = min(scores, key=lambda name: scores[name]["mae"])
    timings, parameters = {}, {}
    for name, model in study_estimators(model_config, study["models"]).items():
        print(f"{fold.name} · {name} · {len(train):,} training rows", flush=True)
        started = time.perf_counter()
        model.fit(train[FEATURES], train.demand)
        predictions[name] = np.maximum(0, model.predict(valid[FEATURES]))
        timings[name] = time.perf_counter() - started
        scores[name] = metrics(valid.demand, predictions[name])
        parameters[name] = {key: str(value) for key, value in model.get_params().items()}
        print(f"  validation MAE={scores[name]['mae']:.5f}", flush=True)
    for name, values in predictions.items():
        result[name] = values
    details = {
        **asdict(fold),
        "effective_train_start": effective_start,
        "effective_train_end_exclusive": effective_end,
        "training_max_target": train.hour.max(),
        "validation_max_target": valid.hour.max(),
        "train_rows": len(train),
        "training_targets_sha256": hashlib.sha256(
            pd.util.hash_pandas_object(train[["zone_id", "hour", "demand"]], index=False)
            .to_numpy()
            .tobytes()
        ).hexdigest(),
        "validation_rows": len(valid),
        "sparse_zone_ids": sparse_ids,
        "metrics": scores,
        "fit_and_predict_seconds": timings,
        "best_baseline": best_baseline,
    }
    return result, details, parameters


def pooled_scores(predictions: pd.DataFrame, names: list[str]) -> dict:
    """Pool prediction errors directly; fold RMSE and R² cannot be averaged."""
    if predictions.duplicated(["zone_id", "hour"]).any():
        raise ValueError("Out-of-fold targets overlap")
    return {name: metrics(predictions.demand, predictions[name]) for name in names}


def slice_scores(predictions: pd.DataFrame, names: list[str]) -> pd.DataFrame:
    """Cohort membership was established in fit_fold; never refit cohorts on validation."""
    records = []
    for fold, frame in predictions.groupby("fold", sort=False):
        for dimension in [
            "borough",
            "local_hour",
            "weekend",
            "rush_hour",
            "zone_cohort",
            "target_cohort",
        ]:
            for value, rows in frame.groupby(dimension):
                for name in names:
                    records.append(
                        {
                            "fold": fold,
                            "model": name,
                            "dimension": dimension,
                            "value": value,
                            "rows": len(rows),
                            "mean_prediction": float(rows[name].mean()),
                            "positive_prediction_fraction": float(rows[name].gt(0).mean()),
                            **metrics(rows.demand, rows[name]),
                        }
                    )
    return pd.DataFrame(records)


def daily_scores(predictions: pd.DataFrame, names: list[str]) -> pd.DataFrame:
    records = []
    local_day = predictions.hour.dt.tz_convert(TIMEZONE).dt.strftime("%Y-%m-%d")
    for (fold, day), rows in predictions.groupby(["fold", local_day]):
        for name in names:
            records.append(
                {
                    "fold": fold,
                    "date_nyc": day,
                    "model": name,
                    "rows": len(rows),
                    "mae": float(abs(rows.demand - rows[name]).mean()),
                }
            )
    return pd.DataFrame(records)


def run_backtest(
    config: dict, root: Path = Path("."), protocol_path: Path = Path("configs/walk_forward.toml")
) -> dict:
    path = protocol_path if protocol_path.is_absolute() else root / protocol_path
    with path.open("rb") as stream:
        protocol = tomllib.load(stream)
    study = protocol["study"]
    if study["sealed_test_start"] != config["split"]["test_start"]:
        raise ValueError("Protocol and dataset must have the same sealed test boundary")
    if study["train_start"] != config["split"]["train_start"]:
        raise ValueError("Protocol and dataset must have the same training origin")
    if study["feature_set"] != "temporal-v1" or study["primary_metric"] != "pooled_mae":
        raise ValueError("Unsupported study feature set or primary metric")
    study_estimators(protocol["model"], study["models"])
    folds = expanding_folds(
        study["train_start"], study["validation_boundaries"], study["sealed_test_start"]
    )
    origin, cutoff = (
        local_boundary(study["train_start"]),
        local_boundary(study["sealed_test_start"]),
    )
    zones = load_zones(root / "data/external/taxi_zone_lookup.csv").zone_id.tolist()
    data_path = root / "data/processed/hourly_demand.parquet"
    data_hash = sha256(data_path)
    panel = read_development_panel(data_path, origin, cutoff)
    require_complete_window(panel, zones, origin, cutoff)
    features = make_features(panel).dropna(subset=FEATURES)
    results, fold_records = [], []
    identifier = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:6]
    artifact_dir = root / "artifacts/backtests" / identifier
    artifact_dir.mkdir(parents=True, exist_ok=False)
    for fold in folds:
        prediction, details, parameters = fit_fold(features, fold, zones, study, protocol["model"])
        prediction.to_parquet(artifact_dir / f"{fold.name}.parquet", index=False)
        results.append(prediction)
        fold_records.append(details)
    combined = pd.concat(results, ignore_index=True)
    names = list(fold_records[0]["metrics"])
    scores = pooled_scores(combined, names)
    output = root / "reports/backtests" / identifier
    output.mkdir(parents=True, exist_ok=False)
    comparison = pd.DataFrame(scores).T.rename_axis("model").sort_values("mae")
    comparison.to_csv(output / "pooled_metrics.csv")
    fold_scores = [
        {"fold": fold["name"], "model": name, **values}
        for fold in fold_records
        for name, values in fold["metrics"].items()
    ]
    pd.DataFrame(fold_scores).to_csv(output / "fold_metrics.csv", index=False)
    slice_scores(combined, names).to_csv(output / "slice_metrics.csv", index=False)
    daily_scores(combined, names).to_csv(output / "daily_mae.csv", index=False)
    if sha256(data_path) != data_hash:
        raise ValueError("Canonical data changed while the backtest was running")
    leader = str(comparison.index[0])
    record = {
        "backtest_id": identifier,
        "created_at": datetime.now(UTC).isoformat(),
        "protocol": protocol,
        "protocol_sha256": sha256(path),
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
        "source_hashes": {
            str(source.relative_to(root)): sha256(source)
            for source in sorted((root / "src").rglob("*.py"))
        },
        "data_sha256": data_hash,
        "lockfile_sha256": sha256(root / "uv.lock"),
        "features": FEATURES,
        "parameters": parameters,
        "folds": fold_records,
        "validation_rows": len(combined),
        "pooled_metrics": scores,
        "development_leader": leader,
        "test_metrics": None,
        "serving_model_changed": False,
        "conclusion": f"Lowest pooled development MAE: {leader}. "
        "No automatic promotion; May sealed.",
    }
    write_json(output / "metrics.json", record)
    write_json(root / "reports/latest_backtest.json", record)
    print(
        f"Completed backtest {identifier}: {leader}, pooled MAE={scores[leader]['mae']:.5f}",
        flush=True,
    )
    return record
