"""Compare fixed classical models against five baselines on April validation."""

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from nyc_mobility.config import write_json
from nyc_mobility.data.download import sha256
from nyc_mobility.evaluation.metrics import metrics
from nyc_mobility.evaluation.splits import chronological_split, local_boundary
from nyc_mobility.features.temporal import FEATURES, NUMERIC_FEATURES, make_features
from nyc_mobility.models.baselines import baseline_predictions


def estimators(config: dict) -> dict:
    def linear(model):
        transform = ColumnTransformer(
            [
                ("zone", OneHotEncoder(handle_unknown="ignore"), ["zone_id"]),
                ("numeric", StandardScaler(), NUMERIC_FEATURES),
            ]
        )
        return make_pipeline(transform, model)

    # There are 262 NYC zones, above histogram boosting's 255-category limit.
    # One-hot encoding preserves every zone without imposing an ordinal rank.
    zone_encoding = ColumnTransformer(
        [
            (
                "zone",
                OneHotEncoder(sparse_output=False, handle_unknown="ignore", dtype=np.float32),
                ["zone_id"],
            ),
            ("numeric", "passthrough", NUMERIC_FEATURES),
        ]
    )
    boosting = make_pipeline(
        zone_encoding,
        HistGradientBoostingRegressor(
            max_iter=config["boosting_iterations"],
            learning_rate=config["learning_rate"],
            max_leaf_nodes=config["max_leaf_nodes"],
            l2_regularization=config["l2_regularization"],
            random_state=config["random_seed"],
            early_stopping=False,
            categorical_features=None,
            max_bins=255,
        ),
    )
    return {
        "linear_regression": linear(LinearRegression()),
        "ridge": linear(Ridge(alpha=10.0, solver="lsqr")),
        "hist_gradient_boosting": boosting,
    }


def train_models(config: dict, root: Path = Path(".")) -> dict:
    path = root / "data/processed/hourly_demand.parquet"
    # Push down the date filter: this stage does not load held-out test labels.
    panel = pd.read_parquet(
        path, filters=[("hour", "<", local_boundary(config["split"]["test_start"]))]
    )
    features = make_features(panel).dropna(subset=FEATURES)
    train, valid = chronological_split(features, config["split"])
    predictions = baseline_predictions(train, valid)
    scores = {name: metrics(valid.demand, values) for name, values in predictions.items()}
    fitted = {}
    zone_categories = sorted(train.zone_id.unique().tolist())
    for name, model in estimators(config["model"]).items():
        x_train, x_valid = train[FEATURES].copy(), valid[FEATURES].copy()
        print(f"Fitting {name}: {len(train):,} training rows", flush=True)
        model.fit(x_train, train.demand)
        prediction = np.maximum(0, model.predict(x_valid))
        predictions[name] = prediction
        scores[name] = metrics(valid.demand, prediction)
        fitted[name] = model
        print(f"{name}: MAE={scores[name]['mae']:.4f}", flush=True)
    champion = min(scores, key=lambda name: scores[name]["mae"])
    best_ml = min(fitted, key=lambda name: scores[name]["mae"])
    identifier = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:6]
    directory = root / "reports/experiments" / identifier
    directory.mkdir(parents=True, exist_ok=False)
    revision = (
        subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=root, check=False
        ).stdout.strip()
        or "uncommitted-bootstrap"
    )
    record = {
        "experiment_id": identifier,
        "created_at": datetime.now(UTC).isoformat(),
        "git_revision": revision,
        "source_hashes": {
            str(source.relative_to(root)): sha256(source)
            for source in sorted((root / "src").rglob("*.py"))
        },
        "config": config,
        "lockfile_sha256": sha256(root / "uv.lock"),
        "dataset": config["data"],
        "data_sha256": sha256(path),
        "feature_set": "temporal-v1",
        "features": FEATURES,
        "split": config["split"],
        "boundary_timezone": "America/New_York",
        "train_rows": len(train),
        "validation_rows": len(valid),
        "effective_train_start_utc": train.hour.min().isoformat(),
        "training_max_target_utc": train.hour.max().isoformat(),
        "validation_min_target_utc": valid.hour.min().isoformat(),
        "parameters": {
            name: {k: str(v) for k, v in model.get_params().items()}
            for name, model in fitted.items()
        },
        "validation_metrics": scores,
        "test_metrics": None,
        "champion": champion,
        "best_ml": best_ml,
        "conclusion": f"Lowest April MAE: {champion}; May test remains sealed.",
        "protocol": "Rolling one-step evaluation; prior actual hours become available each step.",
        "availability_assumption": "Complete prior-hour pickup counts available at hour boundary.",
    }
    write_json(directory / "metrics.json", record)
    write_json(root / "reports/latest_experiment.json", record)
    pd.DataFrame(scores).T.rename_axis("model").to_csv(directory / "comparison.csv")
    result = valid[
        ["zone_id", "hour", "demand", "borough", "local_hour", "weekday", "rush_hour"]
    ].copy()
    for name, prediction in predictions.items():
        result[name] = prediction
    artifacts = root / "artifacts"
    artifacts.mkdir(exist_ok=True)
    result.to_parquet(artifacts / "validation_predictions.parquet", index=False)
    bundle = {
        "model": fitted[best_ml],
        "name": best_ml,
        "champion": champion,
        "features": FEATURES,
        "zone_ids": zone_categories,
        "experiment_id": identifier,
        "training_max_target_utc": record["training_max_target_utc"],
    }
    joblib.dump(bundle, artifacts / "model.joblib")
    write_json(artifacts / "model_metadata.json", {k: v for k, v in bundle.items() if k != "model"})
    print(json.dumps({"champion": champion, "metrics": scores[champion]}, indent=2))
    return record
