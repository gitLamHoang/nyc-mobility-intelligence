"""Six-fit borough ablation against pinned temporal controls, without test access."""

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
from nyc_mobility.features.borough import CONTEXT_FEATURES, STATIC_FEATURES, make_borough_features
from nyc_mobility.features.temporal import make_features
from nyc_mobility.models.borough import BUNDLES, borough_estimator


def validate_protocol(protocol: dict, config: dict) -> list:
    study = protocol["study"]
    if (
        study["train_start"] != config["split"]["train_start"]
        or study["sealed_test_start"] != config["split"]["test_start"]
    ):
        raise ValueError("Borough protocol must match dataset development boundaries")
    expected = {
        "id": "borough-spatial-v1",
        "feature_set": "temporal-borough-v1",
        "primary_metric": "pooled_mae",
        "observation_delay_hours": 0,
        "common_warmup_hours": 174,
        "common_training_embargo_hours": 6,
        "sparse_zone_mean_max": 1.0,
        "bundles": list(BUNDLES),
        "fit_budget": 6,
        "model": "hist_gradient_boosting",
    }
    if any(study.get(key) != value for key, value in expected.items()):
        raise ValueError("Unsupported borough v1 protocol or expanded budget")
    for key in [
        "fit_budget",
        "observation_delay_hours",
        "common_warmup_hours",
        "common_training_embargo_hours",
    ]:
        if type(study[key]) is not int:
            raise ValueError("Fit budget and availability offsets must be integers")
    if protocol["model"] != {
        "random_seed": 42,
        "boosting_iterations": 120,
        "learning_rate": 0.08,
        "max_leaf_nodes": 31,
        "l2_regularization": 1.0,
        "loss": "squared_error",
        "early_stopping": False,
        "max_bins": 255,
    }:
        raise ValueError("Borough estimator settings differ from the frozen budget")
    features = protocol["features"]
    if (
        features["static"] != STATIC_FEATURES
        or features["context"] != CONTEXT_FEATURES
        or features["polygon_features_eligible"] is not False
        or features["lookup_available_at"] != "2024-02-22T21:33:00Z"
    ):
        raise ValueError("Feature bundle or availability differs from the frozen protocol")
    folds = expanding_folds(
        study["train_start"], study["validation_boundaries"], study["sealed_test_start"]
    )
    if len(folds) * len(study["bundles"]) != study["fit_budget"]:
        raise ValueError("Borough protocol exceeds the six-fit budget")
    return folds


def comparisons(scores: dict, records: list[dict]) -> pd.DataFrame:
    rows = []
    for scope, values in [("pooled", scores), *[(r["name"], r["metrics"]) for r in records]]:
        for candidate, reference in [
            ("borough_static", "hist_gradient_boosting"),
            ("borough_context", "hist_gradient_boosting"),
            ("borough_context", "borough_static"),
        ]:
            mae, control = values[candidate]["mae"], values[reference]["mae"]
            rows.append(
                {
                    "scope": scope,
                    "candidate": candidate,
                    "reference": reference,
                    "mae": mae,
                    "reference_mae": control,
                    "delta_mae": mae - control,
                    "relative_reduction_pct": 100 * (1 - mae / control) if control else None,
                }
            )
    return pd.DataFrame(rows)


def fitted_representation(model, train: pd.DataFrame) -> dict:
    transformed = model[0].transform(train.iloc[:1])
    return {
        "input_columns": list(train),
        "input_dtypes": {name: str(dtype) for name, dtype in train.dtypes.items()},
        "transformed_dtype": str(transformed.dtype),
        "transformed_columns": model[0].get_feature_names_out().tolist(),
        "transformed_width": transformed.shape[1],
        "estimator_parameters": model[-1].get_params(),
        "pipeline_parameters": {k: str(v) for k, v in model.get_params().items()},
    }


def run_borough(
    config: dict, root: Path = Path("."), protocol_path: Path = Path("configs/borough_spatial.toml")
) -> dict:
    root = root.resolve()
    path = protocol_path if protocol_path.is_absolute() else root / protocol_path
    protocol = tomllib.loads(path.read_text())
    folds = validate_protocol(protocol, config)
    study, spec = protocol["study"], protocol["features"]
    data_path = root / "data/processed/hourly_demand.parquet"
    lookup = root / "data/external/taxi_zone_lookup.csv"
    inputs = {
        str(path.relative_to(root)): sha256(path),
        str(data_path.relative_to(root)): protocol["control"]["data_sha256"],
        str(lookup.relative_to(root)): spec["lookup_sha256"],
        "src/nyc_mobility/features/temporal.py": spec["temporal_source_sha256"],
        "src/nyc_mobility/features/borough.py": spec["borough_source_sha256"],
        "uv.lock": sha256(root / "uv.lock"),
    }
    for source, expected in inputs.items():
        checked_hash(root / source, expected)
    control, controls = load_control(protocol, root, feature_set="temporal-latency-v1")
    details = {d["name"]: d for d in control["folds"] if d["delay_hours"] == 0}
    if set(controls) != {fold.name for fold in folds} or set(details) != set(controls):
        raise ValueError("Control predictions/details do not cover exactly the declared folds")
    zones = load_zones(lookup)
    origin, cutoff = (
        local_boundary(study["train_start"]),
        local_boundary(study["sealed_test_start"]),
    )
    panel = read_development_panel(data_path, origin, cutoff)
    require_complete_window(panel, zones.zone_id.tolist(), origin, cutoff)
    features = make_borough_features(panel, zones, lookup_available_at=spec["lookup_available_at"])
    temporal = make_features(panel)
    pd.testing.assert_frame_equal(features[list(temporal)], temporal)
    features = features.dropna(subset=BUNDLES["borough_context"])
    if not np.isfinite(features[BUNDLES["borough_context"]]).all().all():
        raise ValueError("Borough predictors must be finite after warm-up")
    # Every control must pass before any candidate fit, including the final fold.
    for fold in folds:
        matched_fold(
            features, fold, zones.zone_id.tolist(), study, controls[fold.name], details[fold.name]
        )
    preserved = [
        "artifacts/model.joblib",
        "artifacts/model_metadata.json",
        "artifacts/validation_predictions.parquet",
        "reports/latest_experiment.json",
        "reports/latest_backtest.json",
        "reports/latest_uncertainty.json",
        "reports/latest_latency.json",
        "reports/latest_xgboost.json",
        "reports/latest_xgboost_uncertainty.json",
        "reports/latest_spatial_preparation.json",
        "reports/api_smoke.json",
        "reports/data_manifest.json",
    ]
    before = {p: sha256(root / p) for p in preserved if (root / p).is_file()}
    source_hashes = {
        str(p.relative_to(root)): sha256(p) for p in sorted((root / "src").rglob("*.py"))
    }
    identifier = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:6]
    artifacts = root / "artifacts/borough" / identifier
    artifacts.mkdir(parents=True, exist_ok=False)
    results, records, prediction_hashes = [], [], {}
    fitted = 0
    for fold in folds:
        train, valid = matched_fold(
            features, fold, zones.zone_id.tolist(), study, controls[fold.name], details[fold.name]
        )
        result = controls[fold.name].copy()
        detail = {**details[fold.name], "fit_and_predict_seconds": {}, "representations": {}}
        detail["metrics"] = {name: detail["metrics"][name] for name in CONTROL_NAMES}
        for bundle in study["bundles"]:
            columns = BUNDLES[bundle]
            print(f"{fold.name} · {bundle} · {len(train):,} training rows", flush=True)
            model = borough_estimator(protocol["model"], bundle)
            started = time.perf_counter()
            model.fit(train[columns], train.demand)
            prediction = np.maximum(0, model.predict(valid[columns]))
            if prediction.shape != (len(valid),) or not np.isfinite(prediction).all():
                raise ValueError("Invalid borough predictions")
            fitted += 1
            detail["fit_and_predict_seconds"][bundle] = time.perf_counter() - started
            result[bundle] = prediction
            detail["metrics"][bundle] = metrics(valid.demand, prediction)
            detail["representations"][bundle] = fitted_representation(model, train[columns])
            print(f"  validation MAE={detail['metrics'][bundle]['mae']:.6f}", flush=True)
        saved = artifacts / f"{fold.name}.parquet"
        result.to_parquet(saved, index=False)
        prediction_hashes[fold.name] = sha256(saved)
        results.append(result)
        records.append(detail)
    if fitted != study["fit_budget"]:
        raise ValueError("Actual fit count differs from the frozen budget")
    combined = pd.concat(results, ignore_index=True)
    names = CONTROL_NAMES + study["bundles"]
    scores = pooled_scores(combined, names)
    days = daily_scores(combined, names)
    for name in names:
        subset = days.loc[days.model.eq(name)]
        if not np.isclose(
            np.average(subset.mae, weights=subset.rows), scores[name]["mae"], rtol=1e-12, atol=1e-12
        ):
            raise ValueError("Daily weighted MAE does not reconcile with pooled predictions")
    for source, expected in {**inputs, **before, **source_hashes}.items():
        checked_hash(root / source, expected)
    load_control(protocol, root, feature_set="temporal-latency-v1")
    output = root / "reports/borough" / identifier
    output.mkdir(parents=True, exist_ok=False)
    pd.DataFrame(scores).T.rename_axis("model").sort_values("mae").to_csv(
        output / "pooled_metrics.csv"
    )
    pd.DataFrame(
        [{"fold": r["name"], "model": n, **v} for r in records for n, v in r["metrics"].items()]
    ).to_csv(output / "fold_metrics.csv", index=False)
    slice_scores(combined, names).to_csv(output / "slice_metrics.csv", index=False)
    days.to_csv(output / "daily_mae.csv", index=False)
    comparisons(scores, records).to_csv(output / "comparison.csv", index=False)
    record = {
        "borough_id": identifier,
        "created_at": datetime.now(UTC).isoformat(),
        "protocol": protocol,
        "protocol_sha256": inputs[str(path.relative_to(root))],
        "input_sha256": inputs,
        "source_hashes": source_hashes,
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
            "sklearn": sklearn.__version__,
            "pandas": pd.__version__,
            "numpy": np.__version__,
        },
        "features": BUNDLES,
        "temporal_columns_identical": True,
        "folds": records,
        "validation_rows": len(combined),
        "pooled_metrics": scores,
        "models_fitted": fitted,
        "control_models_refitted": 0,
        "prediction_sha256": prediction_hashes,
        "preserved_sha256": before,
        "serving_model_changed": False,
        "test_metrics": None,
        "conclusion": "Fixed borough ablation; no serving promotion or test evaluation.",
    }
    write_json(output / "metrics.json", record)
    write_json(root / "reports/latest_borough.json", record)
    print(f"Borough comparison written to {output}", flush=True)
    return record
