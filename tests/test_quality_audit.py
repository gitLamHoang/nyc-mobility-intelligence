"""Artificial boundary fixtures for the forensic audit; never reported observations."""

import json

import duckdb
import numpy as np
import pandas as pd
import pytest

from nyc_mobility.data.download import sha256
from nyc_mobility.data.prepare import densify, prepare
from nyc_mobility.data.quality_audit import (
    audit_month,
    development_range,
    quality_audit,
    reporting_volume_flags,
)


def trip_fixture(month="2026-01"):
    row = {
        "VendorID": 1,
        "tpep_pickup_datetime": pd.Timestamp(f"{month}-20 10:15"),
        "tpep_dropoff_datetime": pd.Timestamp(f"{month}-20 10:30"),
        "PULocationID": 2,
        "DOLocationID": 3,
        "passenger_count": None,
        "trip_distance": 1.2,
        "fare_amount": 10.0,
        "payment_type": 1,
        "extra_source_column": "same",
    }
    return pd.DataFrame(
        [
            row,
            row,
            row,
            {**row, "extra_source_column": "different"},
            {**row, "VendorID": 6},
            {**row, "PULocationID": 264},
            {**row, "PULocationID": 264},
            {**row, "tpep_pickup_datetime": pd.Timestamp("2030-01-01")},
            {**row, "tpep_pickup_datetime": pd.Timestamp("2030-01-01")},
        ]
    )


def test_exact_duplicates_use_all_columns_and_group_equal_nulls(tmp_path):
    path = tmp_path / "trips.parquet"
    trip_fixture().to_parquet(path)
    with duckdb.connect() as connection:
        counts, duplicate, vendors = audit_month(
            connection, path, pd.Timestamp("2026-01-01"), pd.Timestamp("2026-02-01"), [2, 3]
        )
    assert counts.demand.sum() == 5
    assert vendors.demand.sum() == 5
    assert counts.hour.iloc[0] == pd.Timestamp("2026-01-20 15:00Z")
    assert duplicate.duplicate_excess.sum() == 2
    assert duplicate.duplicate_groups.sum() == 1
    assert duplicate.repeated_rows.sum() == 3
    assert duplicate.max_copies.max() == 3


def test_duplicate_free_input_keeps_typed_empty_output(tmp_path):
    path = tmp_path / "trips.parquet"
    trip_fixture().drop_duplicates().to_parquet(path)
    with duckdb.connect() as connection:
        counts, duplicate, vendors = audit_month(
            connection, path, pd.Timestamp("2026-01-01"), pd.Timestamp("2026-02-01"), [2, 3]
        )
    assert counts.demand.sum() == 3
    assert duplicate.empty
    assert isinstance(duplicate.hour.dtype, pd.DatetimeTZDtype)


def volume_fixture():
    hours = pd.date_range("2026-01-01", periods=800, freq="h", tz="UTC")
    return pd.DataFrame({"series": ["city"] * len(hours), "hour": hours, "demand": 100})


def test_reporting_detector_needs_history_and_flags_a_large_drop():
    volumes = volume_fixture()
    volumes.loc[[100, 700], "demand"] = 0
    report = reporting_volume_flags(volumes)
    assert not report.loc[100, "flag"]  # Insufficient prior weekly matches.
    assert report.loc[700, "flag"]
    assert report.loc[700, "historical_median"] == 100
    assert report.loc[700, "reference_matches"] == 4
    assert report.flag.sum() == 1


def test_reporting_reference_never_uses_current_or_future_counts():
    volumes = volume_fixture()
    before = reporting_volume_flags(volumes)
    volumes.loc[volumes.index >= 700, "demand"] = 100000
    after = reporting_volume_flags(volumes)
    pd.testing.assert_series_equal(
        before.loc[:700, "historical_median"], after.loc[:700, "historical_median"]
    )


def test_vendor_series_do_not_share_history():
    city = volume_fixture()
    vendor = city.assign(series="vendor_1", demand=1)
    report = reporting_volume_flags(pd.concat([city, vendor], ignore_index=True))
    assert not report.flag.any()
    assert report.loc[report.series == "vendor_1", "historical_median"].dropna().eq(1).all()
    with pytest.raises(ValueError, match="contiguous"):
        reporting_volume_flags(city.drop(index=10))
    with pytest.raises(ValueError, match="unique"):
        reporting_volume_flags(pd.concat([city, city.iloc[[0]]]))


@pytest.mark.parametrize("bad_count", [np.inf, np.nan, -1.0, 0.5])
def test_reporting_flags_reject_invalid_observations(bad_count):
    volumes = volume_fixture().astype({"demand": float})
    volumes.loc[500, "demand"] = bad_count
    with pytest.raises(ValueError, match="finite nonnegative integers"):
        reporting_volume_flags(volumes)


def test_reporting_flags_reject_misaligned_hours():
    volumes = volume_fixture()
    volumes["hour"] += pd.Timedelta(minutes=30)
    with pytest.raises(ValueError, match="hour boundaries"):
        reporting_volume_flags(volumes)


@pytest.mark.parametrize(
    "defect", ["outside_hour", "outside_zone", "fraction", "negative", "nan", "overflow", "naive"]
)
def test_densify_refuses_silent_count_loss(defect):
    zones = pd.DataFrame({"zone_id": [2], "borough": ["Queens"], "Zone": ["A"]})
    counts = pd.DataFrame(
        {"zone_id": [2], "hour": pd.to_datetime(["2026-01-01 05:00Z"]), "demand": [1.0]}
    )
    if defect == "outside_hour":
        counts["hour"] += pd.Timedelta(hours=24)
    elif defect == "outside_zone":
        counts["zone_id"] = 3
    elif defect == "naive":
        counts["hour"] = counts.hour.dt.tz_localize(None)
    else:
        counts["demand"] = {"fraction": 0.5, "negative": -1, "nan": np.nan, "overflow": 2**31}[
            defect
        ]
    with pytest.raises(ValueError):
        densify(counts, zones, "2026-01-01", "2026-01-02")


def test_audit_excludes_test_files_and_preserves_canonical_artifacts(tmp_path):
    raw = tmp_path / "data/raw"
    external = tmp_path / "data/external"
    raw.mkdir(parents=True)
    external.mkdir()
    lookup = external / "taxi_zone_lookup.csv"
    pd.DataFrame({"LocationID": [2, 3], "Borough": ["Queens", "Bronx"], "Zone": ["A", "B"]}).to_csv(
        lookup, index=False
    )
    paths = [lookup]
    for month in ["2026-01", "2026-02"]:
        path = raw / f"yellow_tripdata_{month}.parquet"
        trip_fixture(month).to_parquet(path)
        paths.append(path)
    prepare({"data": {"start": "2026-01", "end": "2026-02"}}, tmp_path)
    canonical = tmp_path / "data/processed/hourly_demand.parquet"
    original_hash = sha256(canonical)
    (tmp_path / "reports/data_manifest.json").write_text(
        json.dumps([{"file": str(path), "sha256": sha256(path)} for path in paths])
    )
    (tmp_path / "uv.lock").write_text("test fixture lock")
    experiment = tmp_path / "reports/latest_experiment.json"
    experiment.write_text('{"sentinel": "existing model evidence"}')
    config = {
        "data": {"start": "2026-01", "end": "2026-05"},
        "split": {
            "train_start": "2026-01-01",
            "validation_start": "2026-02-01",
            "test_start": "2026-03-01",
            "test_end": "2026-04-01",
        },
    }
    # No March–May raw files exist. Any accidental attempt to audit test data must fail.
    record = quality_audit(config, tmp_path)
    assert record["source_months"] == ["2026-01", "2026-02"]
    assert record["exact_duplicate_excess"] == 4
    assert record["eligible_pickups"] == 10
    assert record["test_metrics"] is None
    assert not record["canonical_labels_changed"]
    assert sha256(canonical) == original_hash
    assert experiment.read_text() == '{"sentinel": "existing model evidence"}'
    assert len(record["baseline_metrics"]["exact_dedup_scenario"]) == 5
    # A corrupt source is caught in preflight before another audit report can be published.
    paths[-1].write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="manifest"):
        quality_audit(config, tmp_path)
    assert len(list((tmp_path / "reports/quality_audits").iterdir())) == 1


def test_default_development_months_stop_before_may():
    from nyc_mobility.config import load_config

    config = load_config()
    names, start, stop = development_range(config)
    assert names == ["2025-12", "2026-01", "2026-02", "2026-03", "2026-04"]
    assert stop == pd.Timestamp("2026-05-01")
    assert start == pd.Timestamp("2025-12-01")
