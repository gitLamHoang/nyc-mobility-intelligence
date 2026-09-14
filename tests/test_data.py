import pandas as pd
import pytest

from nyc_mobility.data.download import months
from nyc_mobility.data.prepare import densify, load_zones, local_hours_to_utc, validate_schema


def test_month_range_crosses_year():
    assert months("2025-12", "2026-02") == ["2025-12", "2026-01", "2026-02"]
    with pytest.raises(ValueError):
        months("2026-02", "2025-12")


def test_missing_schema_fails(tmp_path):
    path = tmp_path / "bad.parquet"
    pd.DataFrame({"wrong": [1]}).to_parquet(path)
    with pytest.raises(ValueError, match="missing columns"):
        validate_schema(path)


def test_local_timezone_conversion_and_dst():
    values = pd.Series(
        pd.to_datetime(
            ["2026-01-01 00:00", "2026-07-01 00:00", "2026-03-08 02:00", "2026-11-01 01:00"]
        )
    )
    converted = local_hours_to_utc(values)
    assert converted.iloc[0] == pd.Timestamp("2026-01-01 05:00Z")
    assert converted.iloc[1] == pd.Timestamp("2026-07-01 04:00Z")
    assert converted.iloc[2:].isna().all()


def test_dense_panel_includes_zeros_but_no_phantom_spring_hour():
    zones = pd.DataFrame({"zone_id": [2, 3], "borough": ["Queens", "Bronx"], "Zone": ["A", "B"]})
    counts = pd.DataFrame(
        {"zone_id": [2], "hour": pd.to_datetime(["2026-03-08 05:00Z"]), "demand": [7]}
    )
    frame = densify(counts, zones, "2026-03-08", "2026-03-09")
    assert len(frame) == 46
    assert frame.demand.sum() == 7
    assert (frame.demand == 0).sum() == 45
    with pytest.raises(ValueError, match="Fall-back"):
        densify(counts, zones, "2026-11-01", "2026-11-02")


def test_geographic_lookup_excludes_ewr_unknown(tmp_path):
    path = tmp_path / "lookup.csv"
    pd.DataFrame(
        {
            "LocationID": [1, 2, 264, 265],
            "Borough": ["EWR", "Queens", "Unknown", "N/A"],
            "Zone": ["Airport", "Jamaica Bay", "Unknown", "Outside"],
        }
    ).to_csv(path, index=False)
    assert load_zones(path).zone_id.tolist() == [2]
