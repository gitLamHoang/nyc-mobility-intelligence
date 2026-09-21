"""Matched chronological sensitivity to delayed observations under a frozen protocol."""

import subprocess
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pandas as pd

from nyc_mobility.config import write_json
from nyc_mobility.data.download import sha256
from nyc_mobility.data.prepare import load_zones
from nyc_mobility.evaluation.backtest import (
    daily_scores,
    fit_fold,
    pooled_scores,
    read_development_panel,
    slice_scores,
)
from nyc_mobility.evaluation.splits import expanding_folds, local_boundary, require_complete_window
from nyc_mobility.features.temporal import FEATURES, effective_lags, make_features


def validate_protocol(protocol: dict, config: dict) -> None:
    study = protocol["study"]
    if (
        study["train_start"] != config["split"]["train_start"]
        or study["sealed_test_start"] != config["split"]["test_start"]
    ):
        raise ValueError("Latency protocol must use the dataset's development boundaries")
    if (
        study["feature_set"] != "temporal-latency-v1"
        or study["primary_metric"] != "pooled_mae"
        or study["model"] != "hist_gradient_boosting"
        or study["delay_hours"] != [0, 1, 3, 6]
        or any(type(d) is not int for d in study["delay_hours"])
    ):
        raise ValueError("Unsupported latency v1 features, model, metric or delay settings")
    if study["common_warmup_hours"] != 174 or study["common_training_embargo_hours"] != 6:
        raise ValueError("Latency v1 requires common 174-hour warm-up and six-hour embargo")


def delay_effects(pooled: list[dict], folds: list[dict], model: str) -> pd.DataFrame:
    """Compare every model setting against this study's matched zero-delay control."""
    rows = [{"scope": "pooled", **r} for r in pooled if r["model"] == model]
    rows.extend({"scope": r["fold"], **r} for r in folds if r["model"] == model)
    controls = {r["scope"]: r["mae"] for r in rows if r["delay_hours"] == 0}
    return pd.DataFrame(
        {
            "scope": r["scope"],
            "delay_hours": r["delay_hours"],
            "model": model,
            "mae": r["mae"],
            "control_mae": controls[r["scope"]],
            "mae_change": r["mae"] - controls[r["scope"]],
            "mae_increase_pct": (
                100 * (r["mae"] / controls[r["scope"]] - 1) if controls[r["scope"]] > 0 else None
            ),
        }
        for r in rows
    )


def run_latency(
    config: dict, root: Path = Path("."), protocol_path: Path = Path("configs/latency.toml")
) -> dict:
    path = protocol_path if protocol_path.is_absolute() else root / protocol_path
    with path.open("rb") as stream:
        protocol = tomllib.load(stream)
    validate_protocol(protocol, config)
    study = protocol["study"]
    folds = expanding_folds(
        study["train_start"], study["validation_boundaries"], study["sealed_test_start"]
    )
    origin, cutoff = (
        local_boundary(study["train_start"]),
        local_boundary(study["sealed_test_start"]),
    )
    zones = load_zones(root / "data/external/taxi_zone_lookup.csv").zone_id.tolist()
    data_path = root / "data/processed/hourly_demand.parquet"
    data_hash, protocol_hash = sha256(data_path), sha256(path)
    panel = read_development_panel(data_path, origin, cutoff)
    require_complete_window(panel, zones, origin, cutoff)
    identifier = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:6]
    artifacts = root / "artifacts/latency" / identifier
    artifacts.mkdir(parents=True, exist_ok=False)
    fit_study = {"models": [study["model"]], "sparse_zone_mean_max": 1.0}
    pooled, fold_rows, slices, days, fold_records = [], [], [], [], []
    control_targets, control_training = None, {}
    for delay in study["delay_hours"]:
        features = make_features(panel, observation_delay_hours=delay).dropna(subset=FEATURES)
        outputs = []
        for fold in folds:
            print(f"Observation delay {delay}h · {fold.name}", flush=True)
            predictions, details, parameters = fit_fold(
                features,
                fold,
                zones,
                fit_study,
                protocol["model"],
                warmup_hours=study["common_warmup_hours"],
                training_embargo_hours=study["common_training_embargo_hours"],
            )
            # The last training interval must have finished and arrived by model-fit time.
            available_at = details["training_max_target"] + pd.Timedelta(hours=1 + delay)
            if available_at > fold.validation_start:
                raise ValueError("Training labels are unavailable at the fold's forecast origin")
            if delay == 0:
                control_training[fold.name] = details["training_targets_sha256"]
            elif details["training_targets_sha256"] != control_training[fold.name]:
                raise ValueError("Training targets differ across delay settings")
            predictions = predictions.rename(columns={"previous_hour": "latest_available"})
            details["metrics"]["latest_available"] = details["metrics"].pop("previous_hour")
            if details["best_baseline"] == "previous_hour":
                details["best_baseline"] = "latest_available"
            details.update(
                delay_hours=delay,
                effective_lags=effective_lags(delay),
                rolling_last_observation_offset_hours=1 + delay,
                last_training_label_available_at=available_at,
            )
            predictions.to_parquet(artifacts / f"delay_{delay}_{fold.name}.parquet", index=False)
            outputs.append(predictions)
            fold_records.append(details)
            fold_rows.extend(
                {"delay_hours": delay, "fold": fold.name, "model": name, **values}
                for name, values in details["metrics"].items()
            )
        combined = pd.concat(outputs, ignore_index=True)
        target_keys = combined[["zone_id", "hour", "demand", "fold", "zone_cohort"]]
        if delay == 0:
            control_targets = target_keys.copy()
        elif not target_keys.equals(control_targets):
            raise ValueError("Validation targets or sparse cohorts differ across settings")
        names = list(details["metrics"])
        scores = pooled_scores(combined, names)
        pooled.extend({"delay_hours": delay, "model": name, **v} for name, v in scores.items())
        slices.append(slice_scores(combined, names).assign(delay_hours=delay))
        days.append(daily_scores(combined, names).assign(delay_hours=delay))
        print(f"Delay {delay}h pooled model MAE={scores[study['model']]['mae']:.5f}", flush=True)
    if sha256(data_path) != data_hash or sha256(path) != protocol_hash:
        raise ValueError("Canonical data or protocol changed during the latency run")
    output = root / "reports/latency" / identifier
    output.mkdir(parents=True, exist_ok=False)
    pd.DataFrame(pooled).to_csv(output / "pooled_metrics.csv", index=False)
    pd.DataFrame(fold_rows).to_csv(output / "fold_metrics.csv", index=False)
    pd.concat(slices, ignore_index=True).to_csv(output / "slice_metrics.csv", index=False)
    pd.concat(days, ignore_index=True).to_csv(output / "daily_mae.csv", index=False)
    effects = delay_effects(pooled, fold_rows, study["model"])
    effects.to_csv(output / "delay_effects.csv", index=False)
    record = {
        "latency_id": identifier,
        "created_at": datetime.now(UTC).isoformat(),
        "protocol": protocol,
        "protocol_sha256": protocol_hash,
        "data_sha256": data_hash,
        "source_hashes": {
            str(p.relative_to(root)): sha256(p) for p in sorted((root / "src").rglob("*.py"))
        },
        "lockfile_sha256": sha256(root / "uv.lock"),
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
        "features": FEATURES,
        "parameters": parameters,
        "folds": fold_records,
        "validation_rows_per_setting": len(control_targets),
        "pooled_metrics": pooled,
        "delay_effects": effects.astype(object).where(effects.notna(), None).to_dict("records"),
        "models_fitted": len(fold_records),
        "serving_model_changed": False,
        "test_metrics": None,
        "conclusion": "Matched development sensitivity only; no new serving artifact or live feed.",
    }
    write_json(output / "metrics.json", record)
    write_json(root / "reports/latest_latency.json", record)
    print(f"Completed latency study {identifier}\n{effects.to_string(index=False)}", flush=True)
    return record
