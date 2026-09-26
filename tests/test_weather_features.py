"""Artificial fixtures check weather availability, not forecasting performance."""

import numpy as np
import pandas as pd
import pytest

from nyc_mobility.features.weather import (
    SNAPSHOT_COLUMNS,
    WEATHER_VALUES,
    weather_snapshots,
)


def observations(times, *, stations=None, temperatures=None):
    count = len(times)
    return pd.DataFrame(
        {
            "station_id": stations if stations is not None else ["JFK"] * count,
            "observed_at": pd.to_datetime(times, utc=True, format="mixed"),
            "temperature_c": temperatures if temperatures is not None else np.arange(count) + 10.0,
            "dew_point_c": np.arange(count) + 1.0,
            "wind_speed_m_s": np.arange(count) + 2.0,
        }
    )


def test_exact_availability_is_excluded_and_same_day_late_reading_is_not_used():
    source = observations(["2026-04-01T08:00Z", "2026-04-01T09:00Z", "2026-04-01T20:00Z"])
    targets = pd.DatetimeIndex(["2026-04-01T10:00Z", "2026-04-01T10:00:01Z"])
    result = weather_snapshots(source, targets, delay_hours=1)
    assert result.temperature_c.tolist() == [10.0, 11.0]
    assert result.observed_at.tolist() == source.observed_at.iloc[:2].tolist()
    assert (result.assumed_available_at < result.hour).all()
    assert result.age_hours.iloc[0] == 2


def test_zero_delay_still_requires_strictly_past_observation():
    source = observations(["2026-04-01T09:59:59Z", "2026-04-01T10:00Z"])
    target = pd.DatetimeIndex(["2026-04-01T10:00Z"])
    result = weather_snapshots(source, target, delay_hours=0)
    assert result.temperature_c.iloc[0] == 10
    assert result.age_hours.iloc[0] == pytest.approx(1 / 3600)


def test_maximum_age_uses_observation_time_with_inclusive_boundary():
    source = observations(["2026-04-01T04:00Z"])
    targets = pd.DatetimeIndex(["2026-04-01T10:00Z", "2026-04-01T10:00:01Z"])
    result = weather_snapshots(source, targets, delay_hours=3)
    assert result.age_hours.iloc[0] == 6
    assert result.temperature_c.iloc[0] == 10
    assert result.iloc[1].drop(labels=["hour", "station_id"]).isna().all()


def test_delay_at_maximum_age_cannot_make_a_qualifying_match():
    source = observations(["2026-04-01T04:00Z"])
    targets = pd.date_range("2026-04-01T10:00Z", periods=2, freq="h")
    result = weather_snapshots(source, targets, delay_hours=6)
    assert result.drop(columns=["hour", "station_id"]).isna().all().all()


def test_no_backfill_before_first_available_observation():
    source = observations(["2026-04-01T10:00Z"])
    targets = pd.date_range("2026-04-01T09:00Z", periods=3, freq="h")
    result = weather_snapshots(source, targets, delay_hours=1)
    assert result.drop(columns=["hour", "station_id"]).isna().all().all()


def test_latest_missing_values_never_fall_back_to_older_nonmissing_values():
    source = observations(["2026-04-01T08:00Z", "2026-04-01T09:00Z"])
    source.loc[1, ["temperature_c", "wind_speed_m_s"]] = np.nan
    targets = pd.DatetimeIndex(["2026-04-01T10:00Z"])
    result = weather_snapshots(source, targets, delay_hours=0)
    assert result.observed_at.iloc[0] == source.observed_at.iloc[1]
    assert np.isnan(result.temperature_c.iloc[0])
    assert np.isnan(result.wind_speed_m_s.iloc[0])
    assert result.dew_point_c.iloc[0] == 2


def test_unavailable_future_values_cannot_influence_past_snapshots():
    source = observations(pd.date_range("2026-04-01T00:00Z", periods=24, freq="h"))
    targets = pd.date_range("2026-04-01T06:00Z", periods=5, freq="h")
    expected = weather_snapshots(source, targets, delay_hours=2)
    perturbed = source.copy()
    unavailable = perturbed.observed_at + pd.Timedelta(2, unit="h") >= targets.max()
    perturbed.loc[unavailable, WEATHER_VALUES] = 1_000_000
    pd.testing.assert_frame_equal(expected, weather_snapshots(perturbed, targets, delay_hours=2))
    shortened = source.loc[~unavailable].copy()
    pd.testing.assert_frame_equal(expected, weather_snapshots(shortened, targets, delay_hours=2))


def test_stations_are_independent_and_input_rows_need_not_be_sorted():
    source = observations(
        ["2026-04-01T09:00Z", "2026-04-01T07:00Z", "2026-04-01T08:00Z"],
        stations=["JFK", "LGA", "JFK"],
        temperatures=[30.0, 20.0, 10.0],
    )
    original = source.copy(deep=True)
    targets = pd.date_range("2026-04-01T09:00Z", periods=2, freq="h")
    result = weather_snapshots(source, targets, delay_hours=0)
    assert list(result.columns) == SNAPSHOT_COLUMNS
    assert result.station_id.tolist() == ["JFK", "JFK", "LGA", "LGA"]
    assert result.temperature_c.tolist() == [10.0, 30.0, 20.0, 20.0]
    assert result.hour.tolist() == list(targets) * 2
    pd.testing.assert_frame_equal(source, original)


@pytest.mark.parametrize("start", ["2026-03-08T05:00Z", "2026-11-01T04:00Z"])
def test_dst_crossings_preserve_elapsed_utc_age(start):
    source = observations(pd.date_range(start, periods=5, freq="h"))
    targets = pd.date_range(pd.Timestamp(start) + pd.Timedelta(2, unit="h"), periods=3, freq="h")
    result = weather_snapshots(source, targets, delay_hours=1)
    assert result.age_hours.tolist() == [2.0, 2.0, 2.0]
    assert result.hour.tolist() == targets.tolist()
    assert result.observed_at.tolist() == source.observed_at.iloc[:3].tolist()


@pytest.mark.parametrize("delay", [-1, 0.5, True, "1", None, np.int64(1)])
def test_invalid_delays_fail(delay):
    source = observations(["2026-04-01T09:00Z"])
    with pytest.raises(ValueError, match="delay_hours"):
        weather_snapshots(source, pd.DatetimeIndex(["2026-04-01T10:00Z"]), delay_hours=delay)


@pytest.mark.parametrize("age", [-1, 0, 1.5, True, "6", None])
def test_invalid_maximum_ages_fail(age):
    source = observations(["2026-04-01T09:00Z"])
    with pytest.raises(ValueError, match="max_age_hours"):
        weather_snapshots(source, pd.DatetimeIndex(["2026-04-01T10:00Z"]), 0, max_age_hours=age)


@pytest.mark.parametrize("column", WEATHER_VALUES)
@pytest.mark.parametrize("value", [np.inf, -np.inf, "broken", True, 1 + 2j])
def test_invalid_weather_values_fail(column, value):
    source = observations(["2026-04-01T09:00Z"])
    source[column] = [value]
    with pytest.raises(ValueError, match=column):
        weather_snapshots(source, pd.DatetimeIndex(["2026-04-01T10:00Z"]), 0)


@pytest.mark.parametrize("timezone", [None, "America/New_York"])
def test_observation_timestamps_require_utc(timezone):
    source = observations(["2026-04-01T09:00Z"])
    source["observed_at"] = source.observed_at.dt.tz_convert(timezone)
    with pytest.raises(ValueError, match="observed_at.*UTC"):
        weather_snapshots(source, pd.DatetimeIndex(["2026-04-01T10:00Z"]), 0)


@pytest.mark.parametrize("timezone", [None, "America/New_York"])
def test_target_timestamps_require_utc(timezone):
    source = observations(["2026-04-01T09:00Z"])
    targets = pd.DatetimeIndex(["2026-04-01T10:00Z"]).tz_convert(timezone)
    with pytest.raises(ValueError, match="targets.*UTC"):
        weather_snapshots(source, targets, 0)


@pytest.mark.parametrize(
    "bad_input", ["observation_nat", "target_nat", "duplicate", "missing_station"]
)
def test_missing_keys_or_duplicate_observations_fail(bad_input):
    source = observations(["2026-04-01T09:00Z"])
    targets = pd.DatetimeIndex(["2026-04-01T10:00Z"])
    if bad_input == "observation_nat":
        source.loc[0, "observed_at"] = pd.NaT
    elif bad_input == "target_nat":
        targets = pd.DatetimeIndex([pd.NaT], tz="UTC")
    elif bad_input == "duplicate":
        source = pd.concat([source, source], ignore_index=True)
    else:
        source.loc[0, "station_id"] = None
    with pytest.raises(ValueError):
        weather_snapshots(source, targets, 0)


@pytest.mark.parametrize("hours", [[10, 10], [11, 10]])
def test_duplicate_or_unsorted_targets_fail(hours):
    source = observations(["2026-04-01T09:00Z"])
    targets = pd.DatetimeIndex([f"2026-04-01T{hour}:00Z" for hour in hours])
    with pytest.raises(ValueError, match="unique and sorted"):
        weather_snapshots(source, targets, 0)


def test_empty_inputs_return_typed_schema():
    source = observations(["2026-04-01T09:00Z"])
    target = pd.DatetimeIndex(["2026-04-01T10:00Z"])
    for frame, hours in [(source.iloc[:0], target), (source, target[:0])]:
        result = weather_snapshots(frame, hours, 0)
        assert result.empty
        assert list(result.columns) == SNAPSHOT_COLUMNS
        assert str(result.observed_at.dtype) == "datetime64[ns, UTC]"
        assert str(result.hour.dtype) == "datetime64[ns, UTC]"


def test_nullable_missing_numeric_values_remain_missing():
    source = observations(["2026-04-01T09:00Z"])
    source["temperature_c"] = pd.Series([pd.NA], dtype="Float64")
    target = pd.DatetimeIndex(["2026-04-01T10:00Z"])
    result = weather_snapshots(source, target, 0)
    assert pd.isna(result.temperature_c.iloc[0])
    assert result.observed_at.iloc[0] == source.observed_at.iloc[0]


def test_different_timestamp_resolutions_join_without_losing_strictness():
    source = observations(["2026-04-01T09:00Z", "2026-04-01T10:00Z"])
    source["observed_at"] = source.observed_at.dt.as_unit("us")
    target = pd.DatetimeIndex(["2026-04-01T10:00Z"]).as_unit("ms")
    assert weather_snapshots(source, target, 0).temperature_c.iloc[0] == 10


def test_missing_columns_and_non_datetime_target_container_fail():
    source = observations(["2026-04-01T09:00Z"])
    target = pd.DatetimeIndex(["2026-04-01T10:00Z"])
    with pytest.raises(ValueError, match="Missing weather columns"):
        weather_snapshots(source.drop(columns="dew_point_c"), target, 0)
    with pytest.raises(ValueError, match="DatetimeIndex"):
        weather_snapshots(source, list(target), 0)


def test_unrepresentable_elapsed_span_fails_explicitly():
    source = observations(["1678-01-01T04:00Z"])
    targets = pd.DatetimeIndex(["2026-04-01T10:00Z"])
    with pytest.raises(ValueError, match="timedelta bounds"):
        weather_snapshots(source, targets, delay_hours=0)
