"""Run with uvicorn nyc_mobility.api.app:app --host 127.0.0.1 --port 8000."""

import os
from functools import lru_cache
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from nyc_mobility.features.temporal import FEATURES, make_features

app = FastAPI(title="NYC Mobility Intelligence", version="0.1.0")


class Observation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hour: AwareDatetime
    demand: int = Field(ge=0, strict=True)


class ForecastRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    zone_id: int = Field(ge=2, le=263, strict=True)
    history: list[Observation] = Field(min_length=168, max_length=744)


@lru_cache(maxsize=1)
def load_bundle() -> dict:
    path = Path(os.environ.get("NYC_MODEL_PATH", "artifacts/model.joblib"))
    if not path.is_file():
        raise HTTPException(status_code=503, detail="Model unavailable; run the training pipeline")
    # Only locally produced trusted artifacts are loaded, never uploaded pickle files.
    return joblib.load(path)


@app.get("/health")
def health() -> dict:
    bundle = load_bundle()
    return {"status": "ok", "model": bundle["name"], "experiment_id": bundle["experiment_id"]}


def predict_one(bundle: dict, request: ForecastRequest) -> dict:
    if request.zone_id not in bundle["zone_ids"]:
        raise ValueError("Zone was not present during training")
    history = pd.DataFrame([item.model_dump() for item in request.history])
    history["hour"] = pd.to_datetime(history.hour, utc=True)
    history["zone_id"] = request.zone_id
    latest = history.hour.max()
    target = latest + pd.Timedelta(hours=1)
    if target <= pd.Timestamp(bundle["training_max_target_utc"]):
        raise ValueError("Forecast target must follow the model training period")
    future = pd.DataFrame({"zone_id": [request.zone_id], "hour": [target], "demand": [np.nan]})
    featured = make_features(
        pd.concat([history, future], ignore_index=True), allow_future_target=True
    )
    inputs = featured.tail(1)[FEATURES]
    if inputs.isna().any().any():
        raise ValueError("At least 168 complete contiguous prior hours are required")
    prediction = float(np.maximum(0, bundle["model"].predict(inputs))[0])
    return {
        "zone_id": request.zone_id,
        "target_hour_utc": target.isoformat(),
        "target_end_utc": (target + pd.Timedelta(hours=1)).isoformat(),
        "latest_observed_hour_utc": latest.isoformat(),
        "predicted_pickups": prediction,
        "model": bundle["name"],
        "experiment_id": bundle["experiment_id"],
        "assumption": "All pickups in the previous hour are available at the forecast boundary",
    }


@app.post("/predict")
def predict(request: ForecastRequest) -> dict:
    try:
        return predict_one(load_bundle(), request)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
