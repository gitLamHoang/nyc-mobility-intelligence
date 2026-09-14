"""Verify the running API against an actual validation prediction and real history."""

import argparse
import json
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

from nyc_mobility.config import write_json


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--zone", type=int, default=237)
    args = parser.parse_args()
    target = pd.Timestamp("2026-04-08T04:00:00Z")
    history = pd.read_parquet(
        "data/processed/hourly_demand.parquet",
        filters=[
            ("zone_id", "==", args.zone),
            ("hour", ">=", target - pd.Timedelta(hours=168)),
            ("hour", "<", target),
        ],
    ).sort_values("hour")
    request = {
        "zone_id": args.zone,
        "history": [
            {"hour": row.hour.isoformat(), "demand": int(row.demand)}
            for row in history.itertuples()
        ],
    }
    Path("work").mkdir(exist_ok=True)
    write_json(Path("work/example_request.json"), request)
    with httpx.Client(timeout=60) as client:
        health = client.get(f"{args.url}/health")
        health.raise_for_status()
        response = client.post(f"{args.url}/predict", json=request)
        response.raise_for_status()
        result = response.json()
        invalid = client.post(
            f"{args.url}/predict", json={**request, "history": request["history"][:-1]}
        )
        if invalid.status_code != 422:
            raise AssertionError("Incomplete history was not rejected")
    offline = pd.read_parquet(
        "artifacts/validation_predictions.parquet",
        filters=[
            ("zone_id", "==", args.zone),
            ("hour", "==", target),
        ],
    )
    if len(offline) != 1:
        raise AssertionError("Expected one matching offline prediction")
    expected = float(offline[result["model"]].iloc[0])
    if not np.isclose(result["predicted_pickups"], expected, rtol=1e-8):
        raise AssertionError("API and offline predictions differ")
    if pd.Timestamp(result["target_hour_utc"]) != target:
        raise AssertionError("API target interval differs")
    evidence = {
        "health": health.json(),
        "response": result,
        "offline_prediction": expected,
        "actual_pickups": int(offline.demand.iloc[0]),
        "history_rows": len(history),
        "short_history_status": invalid.status_code,
        "api_offline_agree": True,
    }
    write_json(Path("reports/api_smoke.json"), evidence)
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
