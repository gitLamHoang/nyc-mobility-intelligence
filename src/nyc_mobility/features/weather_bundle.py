"""A fixed citywide weather feature bundle with explicit missingness and provenance."""

import numpy as np
import pandas as pd
from pandas.api.types import (
    is_bool_dtype,
    is_complex_dtype,
    is_integer_dtype,
    is_numeric_dtype,
)

from nyc_mobility.features.weather import WEATHER_VALUES

WEATHER_STATIONS = {
    "lga": "USW00014732",
    "jfk": "USW00094789",
    "cp": "USW00094728",
}
WEATHER_BUNDLE_FEATURES = [
    feature
    for alias in WEATHER_STATIONS
    for feature in [
        *(f"weather_{alias}_{value}" for value in WEATHER_VALUES),
        *(f"weather_{alias}_{value}_missing" for value in WEATHER_VALUES),
        *(f"weather_{alias}_{value}_unverified" for value in WEATHER_VALUES),
        f"weather_{alias}_age_hours",
    ]
]
QUALITY_STATES = {"good", "unverified", "rejected", "missing"}


def _utc(values: pd.Series | pd.DatetimeIndex, name: str, *, nullable: bool = False) -> None:
    if not isinstance(values.dtype, pd.DatetimeTZDtype) or str(values.dtype.tz) != "UTC":
        raise ValueError(f"{name} must use timezone-aware UTC timestamps")
    if not nullable and values.isna().any():
        raise ValueError(f"{name} must not contain NaT")


def _numeric(values: pd.Series, name: str) -> np.ndarray:
    if (
        not is_numeric_dtype(values.dtype)
        or is_bool_dtype(values.dtype)
        or is_complex_dtype(values.dtype)
    ):
        raise ValueError(f"{name} must contain real numeric values or NaN")
    result = values.to_numpy(dtype=float, na_value=np.nan)
    if np.isinf(result).any():
        raise ValueError(f"{name} must contain finite values or NaN")
    return result


def make_weather_bundle(
    snapshots: pd.DataFrame, targets: pd.DatetimeIndex, delay_hours: int
) -> pd.DataFrame:
    """Return all requested hours and 30 features, with no imputation or row deletion.

    Select the requested delay scenario and require exactly one row per fixed station
    and target. Measurements belong to the selected observation, even when missing;
    quality never selects an older observation. All three stations are shared citywide,
    with no zone assignment. An unverified flag describes uncertain archive quality
    provenance, not a claim that NOAA skipped quality checks.

    Availability is an explicit scenario assumption, not verified publication time.
    The caller supplies source quality states alongside strictly past snapshots. This
    function validates their consistency but cannot verify raw-source classification.
    """
    if type(delay_hours) is not int or delay_hours < 0:
        raise ValueError("delay_hours must be a nonnegative integer")
    if not isinstance(targets, pd.DatetimeIndex):
        raise ValueError("targets must be a DatetimeIndex")
    _utc(targets, "targets")
    if not targets.is_unique or not targets.is_monotonic_increasing:
        raise ValueError("targets must be unique and sorted")
    if not targets.equals(targets.floor("h")) or (
        len(targets) > 1 and not ((targets[1:] - targets[:-1]) == pd.Timedelta(1, unit="h")).all()
    ):
        raise ValueError("targets must be contiguous UTC hour boundaries")
    if not isinstance(snapshots, pd.DataFrame) or not snapshots.columns.is_unique:
        raise ValueError("snapshots must be a DataFrame with unique columns")
    required = {
        "hour",
        "station_id",
        "observed_at",
        "assumed_available_at",
        "age_hours",
        "delay_hours",
        *WEATHER_VALUES,
        *(f"{value}_quality" for value in WEATHER_VALUES),
    }
    if missing := required - set(snapshots.columns):
        raise ValueError(f"Missing weather snapshot columns: {sorted(missing)}")
    delays = snapshots.delay_hours
    if (
        not is_integer_dtype(delays.dtype)
        or is_bool_dtype(delays.dtype)
        or delays.isna().any()
        or delays.lt(0).any()
    ):
        raise ValueError("snapshot delay_hours must contain nonnegative integers")
    frame = snapshots.loc[delays.eq(delay_hours)].copy()
    _utc(frame.hour, "hour")
    for column in ["observed_at", "assumed_available_at"]:
        _utc(frame[column], column, nullable=True)
    if (
        len(frame) != len(WEATHER_STATIONS) * len(targets)
        or not frame.station_id.isin(WEATHER_STATIONS.values()).all()
        or not frame.hour.isin(targets).all()
        or frame.duplicated(["station_id", "hour"]).any()
    ):
        raise ValueError("Snapshots must cover exactly every station/target once for the delay")

    matched = frame.observed_at.notna()
    if not matched.equals(frame.assumed_available_at.notna()):
        raise ValueError("Observation and availability metadata must be missing together")
    frame["age_hours"] = _numeric(frame.age_hours, "age_hours")
    try:
        available = frame.observed_at + pd.Timedelta(delay_hours, unit="h")
        age = (frame.hour - frame.observed_at) / pd.Timedelta(1, unit="h")
    except (OverflowError, ValueError) as error:
        raise ValueError(
            "Weather timestamps and delays must fit pandas timestamp bounds"
        ) from error
    if (
        not frame.loc[matched, "assumed_available_at"].eq(available[matched]).all()
        or not frame.loc[matched, "assumed_available_at"].lt(frame.loc[matched, "hour"]).all()
        or not frame.loc[matched, "age_hours"].between(0, 12, inclusive="right").all()
        or not np.allclose(frame.loc[matched, "age_hours"], age[matched], atol=1e-9, rtol=0)
        or frame.loc[~matched, "age_hours"].notna().any()
    ):
        raise ValueError(
            "Weather metadata must describe a strictly past observation aged at most 12h"
        )

    for value in WEATHER_VALUES:
        frame[value] = _numeric(frame[value], value)
        quality = frame[f"{value}_quality"]
        if not quality.isin(QUALITY_STATES).all():
            raise ValueError(f"{value}_quality contains an unknown quality state")
        accepted = quality.isin(["good", "unverified"])
        if not accepted.equals(frame[value].notna()):
            raise ValueError(f"{value} presence disagrees with its quality state")
        if not quality.loc[~matched].eq("missing").all():
            raise ValueError(f"Unmatched snapshots must have missing {value}_quality")

    output = pd.DataFrame({"hour": targets})
    for alias, station_id in WEATHER_STATIONS.items():
        station = frame.loc[frame.station_id.eq(station_id)].set_index("hour").reindex(targets)
        for value in WEATHER_VALUES:
            name = f"weather_{alias}_{value}"
            output[name] = station[value].to_numpy(dtype=float)
            output[f"{name}_missing"] = station[value].isna().to_numpy(dtype=np.int8)
            output[f"{name}_unverified"] = (
                station[f"{value}_quality"].eq("unverified").to_numpy(dtype=np.int8)
            )
        output[f"weather_{alias}_age_hours"] = station.age_hours.to_numpy(dtype=float)
    return output[["hour", *WEATHER_BUNDLE_FEATURES]]
