"""Prepare citywide weather bundles and verify matched development targets without fitting."""

import json
import subprocess
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd

from nyc_mobility.config import write_json
from nyc_mobility.data.download import sha256
from nyc_mobility.data.prepare import load_zones
from nyc_mobility.evaluation.backtest import read_development_panel
from nyc_mobility.evaluation.controls import checked_hash, load_control, matched_fold
from nyc_mobility.evaluation.splits import expanding_folds, local_boundary, require_complete_window
from nyc_mobility.features.temporal import FEATURES, make_features
from nyc_mobility.features.weather_bundle import WEATHER_BUNDLE_FEATURES, make_weather_bundle


def prepare_weather_features(
    config: dict,
    root: Path = Path("."),
    protocol_path: Path = Path("configs/weather_ablation.toml"),
) -> dict:
    root = root.resolve()
    path = protocol_path if protocol_path.is_absolute() else root / protocol_path
    protocol = tomllib.loads(path.read_text())
    study, weather = protocol["study"], protocol["weather"]
    if (
        study["train_start"] != config["split"]["train_start"]
        or study["sealed_test_start"] != config["split"]["test_start"]
        or study["weather_delays_hours"] != [3, 6]
        or study["fit_budget"] != 6
        or study["common_warmup_hours"] != 174
        or study["common_training_embargo_hours"] != 6
        or study["observation_delay_hours"] != 0
        or weather["features"] != WEATHER_BUNDLE_FEATURES
    ):
        raise ValueError("Weather preparation differs from the bounded comparison contract")
    folds = expanding_folds(
        study["train_start"], study["validation_boundaries"], study["sealed_test_start"]
    )
    if len(folds) != 3:
        raise ValueError("Exactly three development folds are required")
    inputs = {str(path.relative_to(root)): sha256(path), "uv.lock": sha256(root / "uv.lock")}
    inputs.update(
        {str(p.relative_to(root)): sha256(p) for p in sorted((root / "src").rglob("*.py"))}
    )
    inputs["src/nyc_mobility/features/weather_bundle.py"] = weather["bundle_source_sha256"]
    for key in ["metrics", "snapshots"]:
        inputs[weather[key + "_file"]] = weather[key + "_sha256"]
    inputs["data/processed/hourly_demand.parquet"] = protocol["control"]["data_sha256"]
    inputs["data/external/taxi_zone_lookup.csv"] = weather["lookup_sha256"]
    for relative, expected in inputs.items():
        checked_hash(root / relative, expected)
    record = json.loads((root / weather["metrics_file"]).read_text())
    if (
        record["weather_id"] != weather["weather_id"]
        or record["policy"]["quality"] != "documented-sources-with-unverified-v1"
        or record["policy"]["max_age_hours"] != 12
        or record["test_metrics"] is not None
        or record["models_fitted"] != 0
        or record["outputs_sha256"].get(weather["snapshots_file"]) != weather["snapshots_sha256"]
    ):
        raise ValueError("Weather source does not match the declared retrospective policy")
    start, stop = local_boundary(study["train_start"]), local_boundary(study["sealed_test_start"])
    if (
        pd.Timestamp(record["window_start_utc"]) != start
        or pd.Timestamp(record["window_end_utc_exclusive"]) != stop
    ):
        raise ValueError("Weather source window differs from the development window")
    targets = pd.date_range(start, stop, freq="h", inclusive="left")
    snapshots = pd.read_parquet(root / weather["snapshots_file"])
    bundles = {
        delay: make_weather_bundle(snapshots, targets, delay)
        for delay in study["weather_delays_hours"]
    }
    control_spec = protocol["control"]
    control_id = control_spec["latency_id"]
    inputs[f"reports/latency/{control_id}/metrics.json"] = control_spec["metrics_sha256"]
    for fold_name, expected in control_spec["prediction_sha256"].items():
        inputs[f"artifacts/latency/{control_id}/delay_0_{fold_name}.parquet"] = expected
    control, controls = load_control(protocol, root, feature_set="temporal-latency-v1")
    details = {d["name"]: d for d in control["folds"] if d["delay_hours"] == 0}
    if set(controls) != {fold.name for fold in folds} or set(details) != set(controls):
        raise ValueError("Control folds differ from the declared comparison")
    zones = load_zones(root / "data/external/taxi_zone_lookup.csv")
    panel = read_development_panel(root / "data/processed/hourly_demand.parquet", start, stop)
    require_complete_window(panel, zones.zone_id.tolist(), start, stop)
    # Missing weather never changes the row population. Only temporal warm-up is dropped.
    features = make_features(panel).dropna(subset=FEATURES)
    preflight, summary = [], []
    for fold in folds:
        train, valid = matched_fold(
            features, fold, zones.zone_id.tolist(), study, controls[fold.name], details[fold.name]
        )
        for delay, bundle in bundles.items():
            # Unique complete hourly keys establish a many-to-one append for every zone.
            # Avoid materializing two unnecessary full zone-by-weather tables in memory.
            if not train.hour.isin(bundle.hour).all() or not valid.hour.isin(bundle.hour).all():
                raise ValueError("Weather keys would lose control training or validation targets")
            preflight.append(
                {
                    "fold": fold.name,
                    "weather_delay_hours": delay,
                    "training_rows": len(train),
                    "validation_rows": len(valid),
                    "training_targets_sha256": details[fold.name]["training_targets_sha256"],
                    "matched_control_keys_labels_cohorts_scores": True,
                    "weather_filter_rows_removed": 0,
                }
            )
    for delay, bundle in bundles.items():
        if np.isinf(bundle[WEATHER_BUNDLE_FEATURES].to_numpy()).any():
            raise ValueError("Infinite weather predictor")
        for column in WEATHER_BUNDLE_FEATURES:
            summary.append(
                {
                    "delay_hours": delay,
                    "feature": column,
                    "rows": len(bundle),
                    "missing_rows": int(bundle[column].isna().sum()),
                    "min": bundle[column].min(),
                    "max": bundle[column].max(),
                    "mean": bundle[column].mean(),
                }
            )
    for relative, expected in inputs.items():
        checked_hash(root / relative, expected)
    preparation_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:6]
    output = root / "reports/weather_features" / preparation_id
    artifacts = root / "artifacts/weather_features" / preparation_id
    output.mkdir(parents=True)
    artifacts.mkdir(parents=True)
    for delay, bundle in bundles.items():
        bundle.to_parquet(artifacts / f"delay_{delay}.parquet", index=False)
    pd.DataFrame(summary).to_csv(output / "feature_summary.csv", index=False)
    pd.DataFrame(preflight).to_csv(output / "control_preflight.csv", index=False)
    result = {
        "preparation_id": preparation_id,
        "weather_id": record["weather_id"],
        "protocol": protocol,
        "input_source_lock_hashes": inputs,
        "outputs_sha256": {
            str(p.relative_to(root)): sha256(p)
            for p in sorted([*output.glob("*.csv"), *artifacts.glob("*.parquet")])
        },
        "hours_per_bundle": len(targets),
        "weather_features": WEATHER_BUNDLE_FEATURES,
        "validation_rows_per_candidate": sum(len(controls[f.name]) for f in folds),
        "models_fitted": 0,
        "serving_model_changed": False,
        "test_metrics": None,
        "historical_weather_publication_verified": False,
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
    }
    write_json(output / "metrics.json", result)
    write_json(root / "reports/latest_weather_features.json", result)
    print(f"Weather feature preparation: {preparation_id}; no fits; six matched fold/bundle checks")
    return result
