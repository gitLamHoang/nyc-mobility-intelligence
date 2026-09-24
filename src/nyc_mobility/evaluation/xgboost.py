"""Precommitted XGBoost comparison with verified, immutable latency controls."""

import platform
import subprocess
import time
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd
import sklearn
import xgboost

from nyc_mobility.config import write_json
from nyc_mobility.data.download import sha256
from nyc_mobility.data.prepare import load_zones
from nyc_mobility.evaluation.backtest import (
    daily_scores,
    pooled_scores,
    read_development_panel,
    slice_scores,
)
from nyc_mobility.evaluation.controls import CONTROL_NAMES, checked_hash, load_control, matched_fold
from nyc_mobility.evaluation.metrics import metrics
from nyc_mobility.evaluation.splits import expanding_folds, local_boundary, require_complete_window
from nyc_mobility.features.temporal import FEATURES, make_features
from nyc_mobility.models.xgboost import xgboost_estimator


def validate_protocol(protocol: dict, config: dict) -> list:
    study = protocol["study"]
    if (
        study["train_start"] != config["split"]["train_start"]
        or study["sealed_test_start"] != config["split"]["test_start"]
    ):
        raise ValueError("XGBoost protocol must match dataset development boundaries")
    expected = {
        "feature_set": "temporal-latency-v1",
        "primary_metric": "pooled_mae",
        "observation_delay_hours": 0,
        "common_warmup_hours": 174,
        "common_training_embargo_hours": 6,
        "sparse_zone_mean_max": 1.0,
        "max_depths": [4, 6],
        "fit_budget": 6,
        "xgboost_version": "3.4.1",
    }
    if any(study.get(key) != value for key, value in expected.items()):
        raise ValueError("Unsupported XGBoost v1 protocol or expanded fit budget")
    model_expected = {
        "objective": "reg:squarederror",
        "booster": "gbtree",
        "tree_method": "hist",
        "device": "cpu",
        "grow_policy": "depthwise",
        "n_estimators": 120,
        "learning_rate": 0.08,
        "max_bin": 255,
        "min_child_weight": 1.0,
        "reg_lambda": 1.0,
        "reg_alpha": 0.0,
        "gamma": 0.0,
        "subsample": 1.0,
        "colsample_bytree": 1.0,
        "colsample_bylevel": 1.0,
        "colsample_bynode": 1.0,
        "random_state": 42,
        "n_jobs": 4,
        "verbosity": 1,
    }
    if protocol["model"] != model_expected:
        raise ValueError("XGBoost v1 estimator settings differ from the frozen budget")
    folds = expanding_folds(
        study["train_start"], study["validation_boundaries"], study["sealed_test_start"]
    )
    if len(folds) * len(study["max_depths"]) != study["fit_budget"]:
        raise ValueError("XGBoost protocol exceeds the six-fit budget")
    if xgboost.__version__ != study["xgboost_version"]:
        raise ValueError("Installed XGBoost differs from the frozen version")
    return folds


def run_xgboost(
    config: dict, root: Path = Path("."), protocol_path: Path = Path("configs/xgboost.toml")
) -> dict:
    path = protocol_path if protocol_path.is_absolute() else root / protocol_path
    protocol = tomllib.loads(path.read_text())
    folds = validate_protocol(protocol, config)
    study = protocol["study"]
    protocol_hash = sha256(path)
    data_path = root / "data/processed/hourly_demand.parquet"
    checked_hash(data_path, protocol["control"]["data_sha256"])
    control, controls = load_control(protocol, root)
    if set(controls) != {fold.name for fold in folds}:
        raise ValueError("Control predictions do not cover every fold")
    origin = local_boundary(study["train_start"])
    cutoff = local_boundary(study["sealed_test_start"])
    zones = load_zones(root / "data/external/taxi_zone_lookup.csv").zone_id.tolist()
    panel = read_development_panel(data_path, origin, cutoff)
    require_complete_window(panel, zones, origin, cutoff)
    features = make_features(panel, observation_delay_hours=0).dropna(subset=FEATURES)
    details = {d["name"]: d for d in control["folds"] if d["delay_hours"] == 0}
    # Check every fold before spending any of the frozen fitting budget.
    for fold in folds:
        matched_fold(features, fold, zones, study, controls[fold.name], details[fold.name])
    preserved = [
        "artifacts/model.joblib",
        "artifacts/model_metadata.json",
        "artifacts/validation_predictions.parquet",
        "reports/latest_experiment.json",
        "reports/latest_backtest.json",
        "reports/latest_uncertainty.json",
        "reports/latest_latency.json",
        "reports/api_smoke.json",
    ]
    before = {p: sha256(root / p) for p in preserved if (root / p).is_file()}
    identifier = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:6]
    artifacts = root / "artifacts/xgboost" / identifier
    artifacts.mkdir(parents=True, exist_ok=False)
    results, records, parameters, prediction_hashes = [], [], {}, {}
    fitted = 0
    for fold in folds:
        train, valid = matched_fold(
            features, fold, zones, study, controls[fold.name], details[fold.name]
        )
        result = controls[fold.name].copy()
        detail = {**details[fold.name], "fit_and_predict_seconds": {}}
        detail["metrics"] = {name: detail["metrics"][name] for name in CONTROL_NAMES}
        for depth in study["max_depths"]:
            name = f"xgboost_depth{depth}"
            print(f"{fold.name} · {name} · {len(train):,} training rows", flush=True)
            model = xgboost_estimator(protocol["model"], depth)
            started = time.perf_counter()
            model.fit(train[FEATURES], train.demand)
            result[name] = np.maximum(0, model.predict(valid[FEATURES]))
            fitted += 1
            detail["fit_and_predict_seconds"][name] = time.perf_counter() - started
            detail["metrics"][name] = metrics(valid.demand, result[name])
            parameters[name] = {k: str(v) for k, v in model.get_params().items()}
            print(f"  validation MAE={detail['metrics'][name]['mae']:.6f}", flush=True)
        saved_path = artifacts / f"{fold.name}.parquet"
        result.to_parquet(saved_path, index=False)
        prediction_hashes[fold.name] = sha256(saved_path)
        results.append(result)
        records.append(detail)
    if fitted != study["fit_budget"]:
        raise ValueError("Actual fit count differs from the frozen budget")
    combined = pd.concat(results, ignore_index=True)
    names = CONTROL_NAMES + [f"xgboost_depth{d}" for d in study["max_depths"]]
    scores = pooled_scores(combined, names)
    checked_hash(data_path, protocol["control"]["data_sha256"])
    checked_hash(path, protocol_hash)
    for source, expected in before.items():
        checked_hash(root / source, expected)
    load_control(protocol, root)  # Recheck source artifacts after fitting.
    output = root / "reports/xgboost" / identifier
    output.mkdir(parents=True, exist_ok=False)
    pd.DataFrame(scores).T.rename_axis("model").sort_values("mae").to_csv(
        output / "pooled_metrics.csv"
    )
    pd.DataFrame(
        [
            {"fold": fold["name"], "model": name, **values}
            for fold in records
            for name, values in fold["metrics"].items()
        ]
    ).to_csv(output / "fold_metrics.csv", index=False)
    slice_scores(combined, names).to_csv(output / "slice_metrics.csv", index=False)
    daily_scores(combined, names).to_csv(output / "daily_mae.csv", index=False)
    record = {
        "xgboost_id": identifier,
        "created_at": datetime.now(UTC).isoformat(),
        "protocol": protocol,
        "protocol_sha256": protocol_hash,
        "data_sha256": protocol["control"]["data_sha256"],
        "lockfile_sha256": sha256(root / "uv.lock"),
        "source_hashes": {
            str(p.relative_to(root)): sha256(p) for p in sorted((root / "src").rglob("*.py"))
        },
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
        "versions": {
            "python": platform.python_version(),
            "xgboost": xgboost.__version__,
            "sklearn": sklearn.__version__,
            "pandas": pd.__version__,
            "numpy": np.__version__,
        },
        "features": FEATURES,
        "parameters": parameters,
        "folds": records,
        "validation_rows": len(combined),
        "pooled_metrics": scores,
        "models_fitted": fitted,
        "control_models_refitted": 0,
        "prediction_sha256": prediction_hashes,
        "preserved_sha256": before,
        "serving_model_changed": False,
        "test_metrics": None,
        "conclusion": "Development comparison only; no serving promotion or test evaluation.",
    }
    write_json(output / "metrics.json", record)
    write_json(root / "reports/latest_xgboost.json", record)
    print(f"XGBoost comparison written to {output}", flush=True)
    return record
