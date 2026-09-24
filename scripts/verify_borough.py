"""Reconcile the saved borough study and unchanged artifacts without any model fits."""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from nyc_mobility.config import write_json
from nyc_mobility.data.download import sha256
from nyc_mobility.evaluation.controls import CONTROL_NAMES, checked_hash, load_control
from nyc_mobility.evaluation.splits import local_boundary, require_complete_window


def verify(directory: Path) -> dict:
    record = json.loads((directory / "metrics.json").read_text())
    protocol = record["protocol"]
    for group in ["input_sha256", "source_hashes", "preserved_sha256"]:
        for name, expected in record[group].items():
            checked_hash(Path(name), expected)
    _, controls = load_control(protocol, Path("."), feature_set="temporal-latency-v1")
    artifact_dir = Path("artifacts/borough") / record["borough_id"]
    frames = []
    for fold in record["folds"]:
        path = artifact_dir / f"{fold['name']}.parquet"
        checked_hash(path, record["prediction_sha256"][fold["name"]])
        frame = pd.read_parquet(path)
        saved = controls[fold["name"]]
        pd.testing.assert_frame_equal(frame[list(saved)], saved)
        require_complete_window(
            frame,
            sorted(saved.zone_id.unique()),
            pd.Timestamp(fold["validation_start"]),
            pd.Timestamp(fold["validation_end"]),
        )
        frames.append(frame)
    combined = pd.concat(frames, ignore_index=True)
    if combined.hour.max() >= local_boundary(protocol["study"]["sealed_test_start"]):
        raise ValueError("Saved predictions include sealed test targets")
    if combined.duplicated(["zone_id", "hour"]).any() or len(combined) != record["validation_rows"]:
        raise ValueError("Invalid saved target coverage")
    pooled = pd.read_csv(directory / "pooled_metrics.csv").set_index("model")
    folds = pd.read_csv(directory / "fold_metrics.csv").set_index(["fold", "model"])
    days = pd.read_csv(directory / "daily_mae.csv")
    discrepancies = []
    models = CONTROL_NAMES + protocol["study"]["bundles"]
    for scope, frame in [("pooled", combined), *list(combined.groupby("fold"))]:
        for name in models:
            actual, forecast = frame.demand.to_numpy(), frame[name].to_numpy()
            if not np.isfinite(forecast).all() or (forecast < 0).any():
                raise ValueError("Invalid saved predictions")
            mae = float(np.mean(np.abs(actual - forecast)))
            rmse = float(np.sqrt(np.mean((actual - forecast) ** 2)))
            row = pooled.loc[name] if scope == "pooled" else folds.loc[(scope, name)]
            for key, value in [("mae", mae), ("rmse", rmse)]:
                if not np.isclose(value, row[key], rtol=1e-12, atol=1e-12):
                    raise ValueError("Saved metric tables do not reconcile")
                discrepancies.append(abs(value - row[key]))
            if scope == "pooled":
                if not np.isclose(
                    mae, record["pooled_metrics"][name]["mae"], atol=1e-12, rtol=1e-12
                ):
                    raise ValueError("Pooled record does not reconcile")
    daily_checked = 0
    combined["date_nyc"] = combined.hour.dt.tz_convert("America/New_York").dt.strftime("%Y-%m-%d")
    indexed = days.set_index(["fold", "date_nyc", "model"], verify_integrity=True)
    for (fold, day), frame in combined.groupby(["fold", "date_nyc"]):
        for model in models:
            row = indexed.loc[(fold, day, model)]
            expected = np.abs(frame.demand - frame[model]).mean()
            if row.rows != len(frame) or not np.isclose(row.mae, expected, atol=1e-12, rtol=1e-12):
                raise ValueError("Daily coverage or errors do not reconcile")
            daily_checked += 1
    if daily_checked != len(days):
        raise ValueError("Unexpected extra daily records")
    before = {
        **record["preserved_sha256"],
        **{
            name: record["input_sha256"][name]
            for name in ["data/processed/hourly_demand.parquet", "uv.lock"]
        },
    }
    verification = {
        "borough_id": record["borough_id"],
        "unchanged_files_sha256": before,
        "input_source_control_hashes_match": True,
        "control_forecasts_and_targets_identical": True,
        "prediction_hashes_match": True,
        "validation_rows": len(combined),
        "daily_rows_independently_checked": daily_checked,
        "pooled_and_fold_mae_rmse_max_absolute_discrepancy": max(discrepancies),
        "verification_models_fitted": 0,
        "test_metrics": None,
        "verification_script_sha256": sha256(Path(__file__)),
    }
    write_json(directory / "verification.json", verification)
    print(
        json.dumps(
            {k: v for k, v in verification.items() if k != "unchanged_files_sha256"}, indent=2
        )
    )
    return verification


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report_directory", type=Path)
    args = parser.parse_args()
    verify(args.report_directory)
