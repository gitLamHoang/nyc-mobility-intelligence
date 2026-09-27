"""Artificial examples verify alignment and quality semantics, not model performance."""

import numpy as np
import pandas as pd
import pytest

from nyc_mobility.features.weather import WEATHER_VALUES, weather_snapshots
from nyc_mobility.features.weather_bundle import (
    WEATHER_BUNDLE_FEATURES,
    WEATHER_STATIONS,
    make_weather_bundle,
)


def fixture(start="2026-04-01T10:00Z", *, delay=1):
    targets = pd.date_range(start, periods=3, freq="h")
    parts = []
    for offset, station in enumerate(WEATHER_STATIONS.values()):
        observed = targets - pd.Timedelta(delay + 1, unit="h")
        part = pd.DataFrame(
            {
                "hour": targets,
                "station_id": station,
                "observed_at": observed,
                "assumed_available_at": observed + pd.Timedelta(delay, unit="h"),
                "age_hours": float(delay + 1),
                "delay_hours": delay,
            }
        )
        for value in WEATHER_VALUES:
            part[value] = np.arange(3, dtype=float) + offset * 10
            part[f"{value}_quality"] = "good"
        parts.append(part)
    return pd.concat(parts, ignore_index=True), targets


def test_stable_features_and_station_alignment_survive_row_order():
    snapshots, targets = fixture()
    shuffled = snapshots.sample(frac=1, random_state=3)
    original = shuffled.copy(deep=True)
    actual = make_weather_bundle(shuffled, targets, 1)
    assert actual.columns.tolist() == ["hour", *WEATHER_BUNDLE_FEATURES]
    assert len(WEATHER_BUNDLE_FEATURES) == 30
    assert actual.hour.tolist() == targets.tolist()
    for offset, alias in enumerate(WEATHER_STATIONS):
        assert actual[f"weather_{alias}_temperature_c"].tolist() == [
            offset * 10,
            offset * 10 + 1,
            offset * 10 + 2,
        ]
    pd.testing.assert_frame_equal(shuffled, original)
    pd.testing.assert_frame_equal(actual, make_weather_bundle(snapshots, targets, 1))


def test_values_and_age_stay_missing_and_quality_indicators_are_distinct():
    snapshots, targets = fixture()
    snapshots.loc[0, ["observed_at", "assumed_available_at"]] = pd.NaT
    snapshots.loc[0, "age_hours"] = np.nan
    for value in WEATHER_VALUES:
        snapshots.loc[0, value] = np.nan
        snapshots.loc[0, f"{value}_quality"] = "missing"
    snapshots.loc[1, "temperature_c"] = np.nan
    snapshots.loc[1, "temperature_c_quality"] = "rejected"
    snapshots.loc[2, "temperature_c_quality"] = "unverified"
    actual = make_weather_bundle(snapshots, targets, 1)
    assert len(actual) == len(targets)
    assert actual.weather_lga_temperature_c.isna().tolist() == [True, True, False]
    assert actual.weather_lga_temperature_c_missing.tolist() == [1, 1, 0]
    assert actual.weather_lga_temperature_c_unverified.tolist() == [0, 0, 1]
    assert actual.weather_lga_age_hours.isna().tolist() == [True, False, False]
    assert actual.weather_lga_age_hours.iloc[1] == 2


def test_only_requested_delay_scenario_is_selected():
    snapshots, targets = fixture()
    other, _ = fixture(delay=3)
    other["temperature_c"] = 1000.0
    combined = pd.concat([other, snapshots], ignore_index=True)
    pd.testing.assert_frame_equal(
        make_weather_bundle(snapshots, targets, 1), make_weather_bundle(combined, targets, 1)
    )


@pytest.mark.parametrize("start", ["2026-03-08T05:00Z", "2026-11-01T04:00Z"])
def test_dst_crossings_preserve_utc_hours_and_elapsed_age(start):
    snapshots, targets = fixture(start)
    actual = make_weather_bundle(snapshots, targets, 1)
    assert actual.hour.tolist() == targets.tolist()
    assert actual.weather_lga_age_hours.tolist() == [2, 2, 2]


@pytest.mark.parametrize("value", WEATHER_VALUES)
@pytest.mark.parametrize(
    ("quality", "measurement"),
    [("good", np.nan), ("unverified", np.nan), ("rejected", 3.0), ("missing", 3.0)],
)
def test_inconsistent_quality_presence_fails(value, quality, measurement):
    snapshots, targets = fixture()
    snapshots.loc[0, value] = measurement
    snapshots.loc[0, f"{value}_quality"] = quality
    with pytest.raises(ValueError, match="presence disagrees"):
        make_weather_bundle(snapshots, targets, 1)


@pytest.mark.parametrize("quality", ["unchecked", "unknown", "", None, np.nan])
def test_unknown_quality_is_rejected(quality):
    snapshots, targets = fixture()
    snapshots.loc[0, "temperature_c_quality"] = quality
    with pytest.raises(ValueError, match="unknown quality state"):
        make_weather_bundle(snapshots, targets, 1)


@pytest.mark.parametrize("column", [*WEATHER_VALUES, "age_hours"])
@pytest.mark.parametrize("value", [np.inf, -np.inf, "bad", True, 1 + 2j])
def test_nonreal_nonfinite_or_coerced_values_fail(column, value):
    snapshots, targets = fixture()
    snapshots[column] = [value] * len(snapshots)
    with pytest.raises(ValueError, match=column):
        make_weather_bundle(snapshots, targets, 1)


@pytest.mark.parametrize(
    "change", ["omit", "duplicate", "extra_station", "extra_hour", "repeated_station"]
)
def test_station_target_crossproduct_must_be_exact(change):
    snapshots, targets = fixture()
    if change == "omit":
        snapshots = snapshots.iloc[1:]
    elif change == "duplicate":
        snapshots = pd.concat([snapshots, snapshots.iloc[:1]], ignore_index=True)
    elif change == "extra_station":
        snapshots.loc[0, "station_id"] = "OTHER"
    elif change == "extra_hour":
        snapshots.loc[0, "hour"] = targets[-1] + pd.Timedelta(1, unit="h")
    else:
        snapshots.loc[0, "station_id"] = WEATHER_STATIONS["jfk"]
    with pytest.raises(ValueError, match="exactly every station/target"):
        make_weather_bundle(snapshots, targets, 1)


@pytest.mark.parametrize("column", ["hour", "observed_at", "assumed_available_at"])
@pytest.mark.parametrize("timezone", [None, "America/New_York"])
def test_snapshot_timestamps_require_explicit_utc(column, timezone):
    snapshots, targets = fixture()
    snapshots[column] = snapshots[column].dt.tz_convert(timezone)
    with pytest.raises(ValueError, match=f"{column}.*UTC"):
        make_weather_bundle(snapshots, targets, 1)


@pytest.mark.parametrize("change", ["future", "exact", "wrong_delay", "age", "stale", "partial"])
def test_inconsistent_or_unavailable_metadata_fails(change):
    snapshots, targets = fixture()
    if change in {"future", "exact"}:
        available = targets[0] + pd.Timedelta(int(change == "future"), unit="h")
        snapshots.loc[0, "assumed_available_at"] = available
        snapshots.loc[0, "observed_at"] = available - pd.Timedelta(1, unit="h")
        snapshots.loc[0, "age_hours"] = float(change == "exact")
    elif change == "wrong_delay":
        snapshots.loc[0, "assumed_available_at"] += pd.Timedelta(1, unit="m")
    elif change == "age":
        snapshots.loc[0, "age_hours"] = 3.0
    elif change == "stale":
        snapshots.loc[0, "observed_at"] = targets[0] - pd.Timedelta(13, unit="h")
        snapshots.loc[0, "assumed_available_at"] = targets[0] - pd.Timedelta(12, unit="h")
        snapshots.loc[0, "age_hours"] = 13.0
    else:
        snapshots.loc[0, "observed_at"] = pd.NaT
    with pytest.raises(ValueError, match="metadata|strictly past"):
        make_weather_bundle(snapshots, targets, 1)


def test_twelve_hour_age_is_inclusive_and_fractional_age_is_preserved():
    snapshots, targets = fixture()
    for row, age in [(0, 12), (1, 1.25)]:
        snapshots.loc[row, "observed_at"] = targets[row] - pd.Timedelta(age, unit="h")
        snapshots.loc[row, "assumed_available_at"] = targets[row] - pd.Timedelta(age - 1, unit="h")
        snapshots.loc[row, "age_hours"] = age
    assert make_weather_bundle(snapshots, targets, 1).weather_lga_age_hours.tolist() == [
        12,
        1.25,
        2,
    ]


@pytest.mark.parametrize("change", ["gap", "unordered", "duplicate", "minute", "naive", "nat"])
def test_targets_require_contiguous_unique_sorted_utc_hours(change):
    snapshots, targets = fixture()
    if change == "gap":
        targets = targets[[0, 2]]
    elif change == "unordered":
        targets = targets[::-1]
    elif change == "duplicate":
        targets = targets[[0, 0, 1]]
    elif change == "minute":
        targets += pd.Timedelta(1, unit="m")
    elif change == "naive":
        targets = targets.tz_localize(None)
    else:
        targets = pd.DatetimeIndex([pd.NaT], tz="UTC")
    with pytest.raises(ValueError, match="targets"):
        make_weather_bundle(snapshots, targets, 1)


def test_future_source_perturbations_cannot_change_bundled_features():
    _, targets = fixture()
    parts = []
    for station in WEATHER_STATIONS.values():
        parts.append(
            pd.DataFrame(
                {
                    "station_id": station,
                    "observed_at": pd.date_range(
                        targets[0] - pd.Timedelta(4, unit="h"), periods=12, freq="h"
                    ),
                    **{value: np.arange(12, dtype=float) for value in WEATHER_VALUES},
                }
            )
        )
    observations = pd.concat(parts, ignore_index=True)

    def bundle(source):
        snapshots = weather_snapshots(source, targets, delay_hours=1, max_age_hours=12)
        snapshots["delay_hours"] = 1
        for value in WEATHER_VALUES:
            snapshots[f"{value}_quality"] = "good"
        return make_weather_bundle(snapshots, targets, 1)

    expected = bundle(observations)
    future = observations.observed_at + pd.Timedelta(1, unit="h") >= targets.max()
    observations.loc[future, WEATHER_VALUES] = 1_000_000.0
    pd.testing.assert_frame_equal(expected, bundle(observations))


@pytest.mark.parametrize("delay", [-1, True, 1.0, "1", None])
def test_invalid_requested_delay_fails(delay):
    snapshots, targets = fixture()
    with pytest.raises(ValueError, match="delay_hours"):
        make_weather_bundle(snapshots, targets, delay)


@pytest.mark.parametrize("delay", [-1, True, 1.0, "1", None])
def test_invalid_snapshot_delay_fails(delay):
    snapshots, targets = fixture()
    snapshots["delay_hours"] = delay
    with pytest.raises(ValueError, match="delay_hours"):
        make_weather_bundle(snapshots, targets, 1)


def test_empty_targets_with_no_selected_rows_returns_typed_complete_schema():
    snapshots, targets = fixture()
    actual = make_weather_bundle(snapshots.iloc[:0], targets[:0], 1)
    assert actual.empty
    assert actual.columns.tolist() == ["hour", *WEATHER_BUNDLE_FEATURES]
    assert str(actual.hour.dtype) == "datetime64[ns, UTC]"
    assert all(pd.api.types.is_numeric_dtype(actual[name]) for name in WEATHER_BUNDLE_FEATURES)


def test_nullable_numeric_values_are_retained_without_imputation():
    snapshots, targets = fixture()
    snapshots["temperature_c"] = snapshots.temperature_c.astype("Float64")
    snapshots.loc[0, "temperature_c"] = pd.NA
    snapshots.loc[0, "temperature_c_quality"] = "missing"
    assert pd.isna(make_weather_bundle(snapshots, targets, 1).weather_lga_temperature_c.iloc[0])
