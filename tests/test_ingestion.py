import json

import httpx
import pandas as pd
import pytest

from nyc_mobility.data.download import fetch
from nyc_mobility.data.prepare import prepare, validate_schema


def test_download_cache_hash_validation(tmp_path, monkeypatch):
    content = b"official-source-test-fixture"
    calls = []

    def stream(*args, **kwargs):
        from contextlib import nullcontext

        calls.append(args)
        return nullcontext(
            httpx.Response(
                200,
                content=content,
                headers={"content-length": str(len(content))},
                request=httpx.Request("GET", "https://test.invalid/data"),
            )
        )

    monkeypatch.setattr(httpx, "stream", stream)
    path = tmp_path / "data.csv"
    first = fetch("https://test.invalid/data", path)
    assert len(calls) == 1
    assert fetch("https://test.invalid/data", path) == first
    assert len(calls) == 1
    path.write_bytes(b"corrupt")
    fetch("https://test.invalid/data", path)
    assert len(calls) == 2
    assert path.read_bytes() == content


def test_complete_ingestion_conserves_eligible_pickups(tmp_path):
    (tmp_path / "data/raw").mkdir(parents=True)
    (tmp_path / "data/external").mkdir()
    pd.DataFrame(
        {
            "LocationID": [1, 2, 3, 264],
            "Borough": ["EWR", "Queens", "Bronx", "Unknown"],
            "Zone": ["Airport", "A", "B", "Unknown"],
        }
    ).to_csv(tmp_path / "data/external/taxi_zone_lookup.csv", index=False)
    trips = pd.DataFrame(
        {
            "tpep_pickup_datetime": pd.to_datetime(
                [
                    "2026-01-01 00:01",
                    "2026-01-01 00:59",
                    "2026-01-01 01:00",
                    "2026-01-01 02:00",
                    "2026-02-01 00:00",
                    None,
                ]
            ),
            "tpep_dropoff_datetime": pd.to_datetime(["2026-01-01 03:00"] * 6),
            "PULocationID": [2, 2, 3, 264, 2, 2],
            "DOLocationID": [2] * 6,
            "passenger_count": [None, 1, 1, 1, 1, 1],
            "trip_distance": [0, 1, 1, 1, 1, 1],
            "fare_amount": [-1, 10, 10, 10, 10, 10],
            "payment_type": [1] * 6,
        }
    )
    source = tmp_path / "data/raw/yellow_tripdata_2026-01.parquet"
    trips.to_parquet(source)
    panel = prepare({"data": {"start": "2026-01", "end": "2026-01"}}, tmp_path)
    assert len(panel) == 2 * 31 * 24
    assert panel.demand.sum() == 3
    assert (
        panel.loc[
            (panel.zone_id == 2) & (panel.hour == pd.Timestamp("2026-01-01 05:00Z")), "demand"
        ].item()
        == 2
    )
    audit = json.loads((tmp_path / "reports/data_quality.json").read_text())["months"][0]
    assert audit["raw_rows"] == audit["accepted_pickups"] + audit["excluded_pickups"] == 6
    assert audit["accepted_pickups"] == 3
    assert audit["null_pickups"] == 1
    assert audit["negative_fare"] == 1  # Audited, not excluded from the pickup target.
    trips["tpep_pickup_datetime"] = trips.tpep_pickup_datetime.dt.tz_localize("UTC")
    trips.to_parquet(source)
    with pytest.raises(ValueError, match="timezone-naive"):
        validate_schema(source)
