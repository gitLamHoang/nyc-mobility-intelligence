import pandas as pd
from fastapi.testclient import TestClient
from sklearn.dummy import DummyRegressor

from nyc_mobility.api.app import app, load_bundle
from nyc_mobility.features.temporal import FEATURES


def test_prediction_contract_and_shape():
    model = DummyRegressor(strategy="constant", constant=12.5)
    model.fit(pd.DataFrame([[0] * len(FEATURES)], columns=FEATURES), [1])
    app.dependency_overrides.clear()
    original = load_bundle
    import nyc_mobility.api.app as module

    module.load_bundle = lambda: {
        "model": model,
        "name": "unit-test-only",
        "zone_ids": [2],
        "experiment_id": "unit-test-only",
        "training_max_target_utc": "2025-12-31T00:00:00Z",
    }
    try:
        with TestClient(app) as client:
            history = [
                {"hour": time.isoformat(), "demand": 4}
                for time in pd.date_range("2026-01-01", periods=168, freq="h", tz="UTC")
            ]
            body = {"zone_id": 2, "history": history}
            result = client.post("/predict", json=body)
            assert result.status_code == 200
            assert result.json()["predicted_pickups"] == 12.5
            assert result.json()["target_hour_utc"] == "2026-01-08T00:00:00+00:00"
            assert client.get("/health").status_code == 200
            assert client.post("/predict", json={**body, "zone_id": 3}).status_code == 422
            assert (
                client.post("/predict", json={**body, "history": history[:-1]}).status_code == 422
            )
            broken = history.copy()
            broken[10] = {**broken[10], "hour": broken[9]["hour"]}
            assert client.post("/predict", json={**body, "history": broken}).status_code == 422
            naive = [{**item, "hour": item["hour"].replace("+00:00", "")} for item in history]
            assert client.post("/predict", json={**body, "history": naive}).status_code == 422
    finally:
        module.load_bundle = original
