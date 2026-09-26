"""Strictly past weather snapshots under an explicit, assumed reporting delay."""

import numpy as np
import pandas as pd
from pandas.api.types import is_bool_dtype, is_complex_dtype, is_numeric_dtype

WEATHER_VALUES = ["temperature_c", "dew_point_c", "wind_speed_m_s"]
SNAPSHOT_COLUMNS = [
    "hour",
    "station_id",
    "observed_at",
    "assumed_available_at",
    "age_hours",
    *WEATHER_VALUES,
]


def _require_utc(values: pd.Series | pd.DatetimeIndex, name: str) -> None:
    if not isinstance(values.dtype, pd.DatetimeTZDtype) or str(values.dtype.tz) != "UTC":
        raise ValueError(f"{name} must use timezone-aware UTC timestamps")
    if values.isna().any():
        raise ValueError(f"{name} must not contain NaT")


def weather_snapshots(
    observations: pd.DataFrame,
    targets: pd.DatetimeIndex,
    delay_hours: int,
    max_age_hours: int = 6,
) -> pd.DataFrame:
    """Return one row per observed station and target without looking into the future.

    The latest observation whose ``observed_at + delay_hours < hour`` is selected.
    Its elapsed age, measured from observation time, must be at most ``max_age_hours``.
    No qualifying observation produces missing metadata and weather values. Missing
    values on a qualifying observation stay missing; an older complete row is never
    substituted. Inputs are copied, stations retain first-appearance order, and each
    station's output follows the sorted targets. Empty inputs produce an empty frame.

    ``assumed_available_at`` is a scenario assumption, not observed publication time.
    Convert input timestamps explicitly to UTC before calling this function.
    """
    if type(delay_hours) is not int or delay_hours < 0:
        raise ValueError("delay_hours must be a nonnegative integer")
    if type(max_age_hours) is not int or max_age_hours <= 0:
        raise ValueError("max_age_hours must be a positive integer")
    if not isinstance(observations, pd.DataFrame) or not observations.columns.is_unique:
        raise ValueError("observations must be a DataFrame with unique columns")
    missing = {"station_id", "observed_at", *WEATHER_VALUES} - set(observations.columns)
    if missing:
        raise ValueError(f"Missing weather columns: {sorted(missing)}")
    if not isinstance(targets, pd.DatetimeIndex):
        raise ValueError("targets must be a DatetimeIndex")
    _require_utc(targets, "targets")
    _require_utc(observations.observed_at, "observed_at")
    if not targets.is_unique or not targets.is_monotonic_increasing:
        raise ValueError("targets must be unique and sorted")
    if observations.station_id.isna().any():
        raise ValueError("station_id must not be missing")
    if observations.duplicated(["station_id", "observed_at"]).any():
        raise ValueError("Duplicate station/observation time")

    frame = observations[["station_id", "observed_at", *WEATHER_VALUES]].copy()
    for column in WEATHER_VALUES:
        values = frame[column]
        if (
            not is_numeric_dtype(values.dtype)
            or is_bool_dtype(values.dtype)
            or is_complex_dtype(values.dtype)
        ):
            raise ValueError(f"{column} must contain real numeric values or NaN")
        numeric = values.to_numpy(dtype=float, na_value=np.nan)
        if np.isinf(numeric).any():
            raise ValueError(f"{column} must contain finite values or NaN")
        frame[column] = numeric
    try:
        target_frame = pd.DataFrame({"hour": targets.as_unit("ns")})
        frame["observed_at"] = frame.observed_at.astype("datetime64[ns, UTC]")
        frame["assumed_available_at"] = frame.observed_at + pd.Timedelta(delay_hours, unit="h")
        maximum_age = pd.Timedelta(max_age_hours, unit="h")
        available_tolerance = pd.Timedelta(max(max_age_hours - delay_hours, 0), unit="h")
    except (OverflowError, ValueError) as error:
        raise ValueError(
            "Weather timestamps and delays must fit pandas timestamp bounds"
        ) from error

    empty = target_frame.iloc[:0].copy()
    empty["station_id"] = frame.station_id.iloc[:0].reset_index(drop=True)
    for column in ["observed_at", "assumed_available_at"]:
        empty[column] = pd.Series([], dtype="datetime64[ns, UTC]")
    for column in ["age_hours", *WEATHER_VALUES]:
        empty[column] = pd.Series([], dtype=float)
    if frame.empty or targets.empty:
        return empty[SNAPSHOT_COLUMNS]

    result = []
    for station_id, station in frame.groupby("station_id", sort=False, observed=True):
        snapshot = pd.merge_asof(
            target_frame,
            station.drop(columns="station_id").sort_values("assumed_available_at"),
            left_on="hour",
            right_on="assumed_available_at",
            direction="backward",
            allow_exact_matches=False,
            # Subtract the assumed delay so tolerance is measured from observation time.
            # Zero tolerance plus a strict match also excludes delay >= maximum age.
            tolerance=available_tolerance,
        )
        try:
            age = snapshot.hour - snapshot.observed_at
        except OverflowError as error:
            raise ValueError("Weather elapsed ages must fit pandas timedelta bounds") from error
        stale = age > maximum_age
        snapshot.loc[stale, ["observed_at", "assumed_available_at"]] = pd.NaT
        snapshot.loc[stale, WEATHER_VALUES] = np.nan
        snapshot["age_hours"] = age.where(~stale) / pd.Timedelta(1, unit="h")
        snapshot["station_id"] = station_id
        result.append(snapshot[SNAPSHOT_COLUMNS])
    return pd.concat(result, ignore_index=True)
