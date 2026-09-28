"""Six-fit conditional weather comparison, with fixed controls and no test access."""

import hashlib
import json
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
from nyc_mobility.evaluation.borough import fitted_representation
from nyc_mobility.evaluation.controls import CONTROL_NAMES, checked_hash, load_control, matched_fold
from nyc_mobility.evaluation.metrics import metrics
from nyc_mobility.evaluation.splits import expanding_folds, local_boundary, require_complete_window
from nyc_mobility.features.temporal import FEATURES, make_features
from nyc_mobility.features.weather_bundle import WEATHER_BUNDLE_FEATURES, make_weather_bundle
from nyc_mobility.models.weather import BUNDLES, DELAYS, weather_estimator


def validate_protocol(protocol: dict, config: dict) -> list:
    """Reject expanded fit budgets, changed features and altered availability rules."""
    study = protocol["study"]
    if (
        study["train_start"] != config["split"]["train_start"]
        or study["sealed_test_start"] != config["split"]["test_start"]
    ):
        raise ValueError("Weather protocol must match dataset development boundaries")
    expected = {
        "id": "weather-citywide-v1",
        "feature_set": "temporal-citywide-weather-v1",
        "observation_delay_hours": 0,
        "weather_delays_hours": [3, 6],
        "primary_weather_delay_hours": 3,
        "primary_metric": "pooled_mae",
        "common_warmup_hours": 174,
        "common_training_embargo_hours": 6,
        "sparse_zone_mean_max": 1.0,
        "fit_budget": 6,
        "model": "hist_gradient_boosting",
        "missing_weather": "retain NaN; no row exclusions or imputation",
        "scope": "conditional retrospective archive sensitivity; "
        "no verified publication availability",
    }
    if any(study.get(key) != value for key, value in expected.items()):
        raise ValueError("Unsupported weather v1 protocol or expanded budget")
    for key in [
        "fit_budget",
        "observation_delay_hours",
        "primary_weather_delay_hours",
        "common_warmup_hours",
        "common_training_embargo_hours",
    ]:
        if type(study[key]) is not int:
            raise ValueError("Fit budget and availability offsets must be integers")
    if any(type(value) is not int for value in study["weather_delays_hours"]):
        raise ValueError("Weather delays must be integers")
    model = {
        "random_seed": 42,
        "boosting_iterations": 120,
        "learning_rate": 0.08,
        "max_leaf_nodes": 31,
        "l2_regularization": 1.0,
        "loss": "squared_error",
        "early_stopping": False,
        "max_bins": 255,
    }
    if protocol["model"] != model or any(
        type(protocol["model"][key]) is not type(value) for key, value in model.items()
    ):
        raise ValueError("Weather estimator settings differ from the frozen budget")
    if protocol["weather"]["features"] != WEATHER_BUNDLE_FEATURES:
        raise ValueError("Weather feature order differs from the frozen bundle")
    folds = expanding_folds(
        study["train_start"], study["validation_boundaries"], study["sealed_test_start"]
    )
    if len(folds) * len(DELAYS) != study["fit_budget"] or (
        study["validation_boundaries"][-1] != study["sealed_test_start"]
    ):
        raise ValueError("Weather comparison requires exactly three complete development folds")
    return folds


def append_weather(temporal: pd.DataFrame, bundle: pd.DataFrame) -> pd.DataFrame:
    """Append one hourly bundle many-to-one, preserving order, dtypes and missing values."""
    if (
        not temporal.columns.is_unique
        or list(bundle) != ["hour", *WEATHER_BUNDLE_FEATURES]
        or bundle.hour.isna().any()
        or bundle.hour.duplicated().any()
        or not temporal.hour.isin(bundle.hour).all()
        or set(WEATHER_BUNDLE_FEATURES).intersection(temporal.columns)
    ):
        raise ValueError("Weather append requires unique complete hourly keys and new columns")
    weather = bundle.set_index("hour").reindex(temporal.hour)
    weather.index = temporal.index
    result = pd.concat([temporal, weather], axis=1)
    pd.testing.assert_frame_equal(result[list(temporal)], temporal)
    if np.isinf(result[WEATHER_BUNDLE_FEATURES].to_numpy(dtype=float)).any():
        raise ValueError("Infinite weather predictor")
    return result


def comparisons(scores: dict, records: list[dict]) -> pd.DataFrame:
    rows = []
    for scope, values in [("pooled", scores), *[(r["name"], r["metrics"]) for r in records]]:
        for candidate, reference in [
            ("weather_3h", "hist_gradient_boosting"),
            ("weather_6h", "hist_gradient_boosting"),
            ("weather_6h", "weather_3h"),
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


def _preserved(root: Path) -> dict:
    previous = root / "reports/weather_features/20260927T200154Z-823e9c/verification.json"
    before = (
        json.loads(previous.read_text())["unchanged_files_sha256"] if previous.is_file() else {}
    )
    extra = [
        "artifacts/model.joblib",
        "artifacts/model_metadata.json",
        "artifacts/validation_predictions.parquet",
        "reports/latest_latency.json",
        "reports/latest_weather_policy.json",
        "reports/latest_weather_features.json",
        "reports/weather_features/20260927T200154Z-823e9c/metrics.json",
        "reports/weather_features/20260927T200154Z-823e9c/verification.json",
        "artifacts/weather_features/20260927T200154Z-823e9c/delay_3.parquet",
        "artifacts/weather_features/20260927T200154Z-823e9c/delay_6.parquet",
        "configs/weather_inputs_v2.toml",
        "configs/weather_ablation.toml",
        "docs/WEATHER_ABLATION_PROTOCOL.md",
        "uv.lock",
    ]
    for relative in extra:
        if relative not in before and (root / relative).is_file():
            before[relative] = sha256(root / relative)
    for relative, expected in before.items():
        checked_hash(root / relative, expected)
    return before


def _weather_inputs(protocol: dict, root: Path, inputs: dict) -> dict:
    weather = protocol["weather"]
    inputs.update(
        {
            weather["metrics_file"]: weather["metrics_sha256"],
            weather["snapshots_file"]: weather["snapshots_sha256"],
            "data/processed/hourly_demand.parquet": protocol["control"]["data_sha256"],
            "data/external/taxi_zone_lookup.csv": weather["lookup_sha256"],
            "src/nyc_mobility/features/weather_bundle.py": weather["bundle_source_sha256"],
            "configs/weather_inputs.toml": weather["legacy_spec_sha256"],
            "docs/WEATHER_SOURCE_POLICY.md": weather["legacy_policy_sha256"],
        }
    )
    for relative, expected in inputs.items():
        checked_hash(root / relative, expected)
    record = json.loads((root / weather["metrics_file"]).read_text())
    if (
        record["weather_id"] != weather["weather_id"]
        or record["policy"]["quality"] != "documented-sources-with-unverified-v1"
        or record["policy"]["max_age_hours"] != 12
        or not set(DELAYS.values()).issubset(record["policy"]["delays_hours"])
        or record["test_metrics"] is not None
        or record["models_fitted"] != 0
        or record.get("historical_publication_times_verified") is not False
        or record.get("eligible_for_point_in_time_model_claim") is not False
        or record["outputs_sha256"].get(weather["snapshots_file"]) != weather["snapshots_sha256"]
    ):
        raise ValueError("Weather source differs from the frozen conditional archive policy")
    study = protocol["study"]
    if pd.Timestamp(record["window_start_utc"]) != local_boundary(
        study["train_start"]
    ) or pd.Timestamp(record["window_end_utc_exclusive"]) != local_boundary(
        study["sealed_test_start"]
    ):
        raise ValueError("Weather source window differs from the development window")
    # The historical source implementation is evidence, not a demand to revert later code.
    # Raw archives, policy specs and documentation must retain their audited bytes.
    for relative, expected in record.get("input_source_lock_hashes", {}).items():
        if not relative.startswith("src/"):
            checked_hash(root / relative, expected)
            inputs[relative] = expected
    for relative, expected in record["outputs_sha256"].items():
        checked_hash(root / relative, expected)
        inputs[relative] = expected
    return record


def run_weather(
    config: dict,
    root: Path = Path("."),
    protocol_path: Path = Path("configs/weather_ablation.toml"),
) -> dict:
    root = root.resolve()
    path = protocol_path if protocol_path.is_absolute() else root / protocol_path
    protocol = tomllib.loads(path.read_text())
    folds = validate_protocol(protocol, config)
    study, weather = protocol["study"], protocol["weather"]
    inputs = {str(path.relative_to(root)): sha256(path), "uv.lock": sha256(root / "uv.lock")}
    source_record = _weather_inputs(protocol, root, inputs)
    control, controls = load_control(protocol, root, feature_set="temporal-latency-v1")
    estimator_source = "src/nyc_mobility/models/train.py"
    if estimator_source in control["source_hashes"]:
        expected = control["source_hashes"][estimator_source]
        checked_hash(root / estimator_source, expected)
        inputs[estimator_source] = expected
    control_spec = protocol["control"]
    control_id = control_spec["latency_id"]
    inputs[f"reports/latency/{control_id}/metrics.json"] = control_spec["metrics_sha256"]
    for fold_name, expected in control_spec["prediction_sha256"].items():
        inputs[f"artifacts/latency/{control_id}/delay_0_{fold_name}.parquet"] = expected
    details = {d["name"]: d for d in control["folds"] if d["delay_hours"] == 0}
    if set(controls) != {fold.name for fold in folds} or set(details) != set(controls):
        raise ValueError("Control predictions/details must cover exactly the declared folds")
    before = _preserved(root)
    source_hashes = {
        str(p.relative_to(root)): sha256(p) for p in sorted((root / "src").rglob("*.py"))
    }
    origin, cutoff = (
        local_boundary(study["train_start"]),
        local_boundary(study["sealed_test_start"]),
    )
    targets = pd.date_range(origin, cutoff, freq="h", inclusive="left")
    snapshots = pd.read_parquet(root / weather["snapshots_file"])
    bundles = {
        name: make_weather_bundle(snapshots, targets, delay) for name, delay in DELAYS.items()
    }
    del snapshots
    zones = load_zones(root / "data/external/taxi_zone_lookup.csv")
    panel = read_development_panel(root / "data/processed/hourly_demand.parquet", origin, cutoff)
    require_complete_window(panel, zones.zone_id.tolist(), origin, cutoff)
    temporal = make_features(panel).dropna(subset=FEATURES)
    del panel
    # Validate every fold and both actual appended bundles before spending any fit budget.
    preflight = []
    for fold in folds:
        train, valid = matched_fold(
            temporal, fold, zones.zone_id.tolist(), study, controls[fold.name], details[fold.name]
        )
        for name, bundle in bundles.items():
            enriched_train, enriched_valid = (
                append_weather(train, bundle),
                append_weather(valid, bundle),
            )
            preflight.append(
                {
                    "fold": fold.name,
                    "model": name,
                    "weather_delay_hours": DELAYS[name],
                    "training_rows": len(enriched_train),
                    "validation_rows": len(enriched_valid),
                    "training_targets_sha256": details[fold.name]["training_targets_sha256"],
                    "matched_control_keys_labels_cohorts_scores": True,
                    "weather_filter_rows_removed": 0,
                    "training_missing_weather_cells": int(
                        enriched_train[WEATHER_BUNDLE_FEATURES].isna().sum().sum()
                    ),
                    "validation_missing_weather_cells": int(
                        enriched_valid[WEATHER_BUNDLE_FEATURES].isna().sum().sum()
                    ),
                }
            )
            del enriched_train, enriched_valid
    identifier = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:6]
    artifacts = root / "artifacts/weather_ablation" / identifier
    output = root / "reports/weather_ablation" / identifier
    artifacts.mkdir(parents=True, exist_ok=False)
    metadata = {
        "weather_ablation_id": identifier,
        "created_at": datetime.now(UTC).isoformat(),
        "protocol": protocol,
        "protocol_sha256": inputs[str(path.relative_to(root))],
        "config": config,
        "config_sha256": hashlib.sha256(
            json.dumps(config, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "lockfile_sha256": inputs["uv.lock"],
        "input_sha256": inputs,
        "source_hashes": source_hashes,
        "preserved_sha256": before,
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
        "weather_features": WEATHER_BUNDLE_FEATURES,
        "weather_policy": source_record["policy"],
        "historical_weather_publication_verified": False,
        "temporal_columns_identical": True,
        "weather_filter_rows_removed": 0,
        "control_models_refitted": 0,
        "serving_model_changed": False,
        "test_metrics": None,
    }
    results, records, attempts, prediction_hashes = [], [], [], {}
    fitted = 0
    try:
        for fold in folds:
            train, valid = matched_fold(
                temporal,
                fold,
                zones.zone_id.tolist(),
                study,
                controls[fold.name],
                details[fold.name],
            )
            result = controls[fold.name].copy()
            detail = {**details[fold.name], "fit_and_predict_seconds": {}, "representations": {}}
            detail["metrics"] = {name: detail["metrics"][name] for name in CONTROL_NAMES}
            for name, bundle in bundles.items():
                x_train = append_weather(train, bundle)[BUNDLES[name]]
                x_valid = append_weather(valid, bundle)[BUNDLES[name]]
                model = weather_estimator(protocol["model"], name)
                print(f"{fold.name} · {name} · {len(train):,} training rows", flush=True)
                attempt = {"fold": fold.name, "model": name, "status": "started"}
                attempts.append(attempt)
                started = time.perf_counter()
                try:
                    model.fit(x_train, train.demand)
                    fitted += 1
                    attempt["fit_completed"] = True
                    prediction = np.maximum(0, model.predict(x_valid))
                    if prediction.shape != (len(valid),) or not np.isfinite(prediction).all():
                        raise ValueError("Invalid weather predictions")
                    detail["representations"][name] = fitted_representation(model, x_train)
                    attempt["status"] = "completed"
                finally:
                    elapsed = time.perf_counter() - started
                    attempt["fit_and_predict_seconds"] = elapsed
                detail["fit_and_predict_seconds"][name] = elapsed
                detail["metrics"][name] = metrics(valid.demand, prediction)
                result[name] = prediction
                print(f"  validation MAE={detail['metrics'][name]['mae']:.6f}", flush=True)
                del model, x_train, x_valid
            saved = artifacts / f"{fold.name}.parquet"
            result.to_parquet(saved, index=False)
            prediction_hashes[fold.name] = sha256(saved)
            results.append(result)
            records.append(detail)
        if fitted != study["fit_budget"]:
            raise ValueError("Actual fit count differs from the frozen weather budget")
        combined = pd.concat(results, ignore_index=True)
        names = CONTROL_NAMES + list(BUNDLES)
        scores = pooled_scores(combined, names)
        days = daily_scores(combined, names)
        days["absolute_error_sum"] = days.rows * days.mae
        for name in names:
            subset = days.loc[days.model.eq(name)]
            if not np.isclose(
                np.average(subset.mae, weights=subset.rows),
                scores[name]["mae"],
                rtol=1e-12,
                atol=1e-12,
            ):
                raise ValueError("Daily weighted MAE does not reconcile with pooled predictions")
        for source, expected in {**inputs, **before, **source_hashes}.items():
            checked_hash(root / source, expected)
        load_control(protocol, root, feature_set="temporal-latency-v1")
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
        pd.DataFrame(preflight).to_csv(output / "preflight.csv", index=False)
        record = {
            **metadata,
            "status": "completed",
            "folds": records,
            "fit_attempts": attempts,
            "models_fitted": fitted,
            "fits_attempted": len(attempts),
            "validation_rows": len(combined),
            "pooled_metrics": scores,
            "prediction_sha256": prediction_hashes,
            "outputs_sha256": {
                str(p.relative_to(root)): sha256(p) for p in sorted(output.glob("*.csv"))
            },
            "conclusion": "Fixed conditional retrospective weather ablation. "
            "No significance claim, serving promotion or test evaluation.",
        }
        write_json(output / "metrics.json", record)
        write_json(root / "reports/latest_weather_ablation.json", record)
    except BaseException as error:
        write_json(
            output / "failure.json",
            {
                **metadata,
                "status": "failed",
                "failed_at": datetime.now(UTC).isoformat(),
                "error_type": type(error).__name__,
                "error": str(error),
                "models_fitted": fitted,
                "fits_attempted": len(attempts),
                "fit_attempts": attempts,
                "folds_completed": records,
                "prediction_sha256": prediction_hashes,
                "replacement_fits_authorized": False,
            },
        )
        raise
    print(f"Weather comparison written to {output}", flush=True)
    return record
