"""Each row forecasts [hour, hour+1h) using observations strictly before hour."""

import numpy as np
import pandas as pd

from nyc_mobility.config import TIMEZONE

LAGS = (1, 2, 3, 24, 168)
NUMERIC_FEATURES = [
    *(f"lag_{lag}" for lag in LAGS),
    "rolling_mean_3",
    "rolling_mean_24",
    "rolling_mean_168",
    "rolling_std_24",
    "trend_1",
    "hour_sin",
    "hour_cos",
    "weekday_sin",
    "weekday_cos",
    "weekend",
    "month",
    "rush_hour",
]
FEATURES = ["zone_id", *NUMERIC_FEATURES]


def validate_panel(frame: pd.DataFrame, allow_future_target: bool = False) -> pd.DataFrame:
    missing = {"zone_id", "hour", "demand"} - set(frame.columns)
    if missing:
        raise ValueError(f"Missing panel columns: {sorted(missing)}")
    result = frame.sort_values(["zone_id", "hour"]).reset_index(drop=True).copy()
    if not isinstance(result.hour.dtype, pd.DatetimeTZDtype):
        raise ValueError("hour must be timezone-aware")
    result["hour"] = result.hour.dt.tz_convert("UTC")
    if result.hour.isna().any() or not result.hour.eq(result.hour.dt.floor("h")).all():
        raise ValueError("Timestamps must be nonmissing hour boundaries")
    if result.duplicated(["zone_id", "hour"]).any():
        raise ValueError("Duplicate zone-hour")
    if not result.zone_id.between(1, 263).all() or (result.zone_id % 1 != 0).any():
        raise ValueError("Invalid Taxi Zone ID")
    if result.zone_id.eq(1).any():
        raise ValueError("Newark Airport is outside the NYC prediction scope")
    gaps = result.groupby("zone_id").hour.diff().dropna()
    if not gaps.eq(pd.Timedelta(hours=1)).all():
        raise ValueError("Each zone must have contiguous hourly history")
    if not allow_future_target and result.demand.isna().any():
        raise ValueError("Missing observed demand")
    observed = result.demand.dropna().to_numpy()
    if not np.isfinite(observed).all() or (observed < 0).any() or (observed % 1 != 0).any():
        raise ValueError("Demand must contain finite nonnegative counts")
    if allow_future_target:
        missing_target = result.demand.isna()
        last_rows = result.groupby("zone_id").tail(1).index
        if not result.index[missing_target].isin(last_rows).all():
            raise ValueError("Only the final target for each zone may be missing")
    return result


def make_features(frame: pd.DataFrame, allow_future_target: bool = False) -> pd.DataFrame:
    result = validate_panel(frame, allow_future_target)
    groups = result.groupby("zone_id", sort=False)["demand"]
    for lag in LAGS:
        result[f"lag_{lag}"] = groups.shift(lag)
    for window in (3, 24, 168):
        result[f"rolling_mean_{window}"] = groups.transform(
            lambda series, w=window: series.shift(1).rolling(w, min_periods=w).mean()
        )
    result["rolling_std_24"] = groups.transform(
        lambda series: series.shift(1).rolling(24, min_periods=24).std(ddof=0)
    )
    result["trend_1"] = result.lag_1 - result.lag_2
    local = result.hour.dt.tz_convert(TIMEZONE)
    result["local_hour"] = local.dt.hour
    result["weekday"] = local.dt.dayofweek
    result["hour_sin"] = np.sin(2 * np.pi * local.dt.hour / 24)
    result["hour_cos"] = np.cos(2 * np.pi * local.dt.hour / 24)
    result["weekday_sin"] = np.sin(2 * np.pi * local.dt.dayofweek / 7)
    result["weekday_cos"] = np.cos(2 * np.pi * local.dt.dayofweek / 7)
    result["weekend"] = (local.dt.dayofweek >= 5).astype("int8")
    result["month"] = local.dt.month
    result["rush_hour"] = (
        (local.dt.dayofweek < 5) & local.dt.hour.isin([7, 8, 9, 16, 17, 18])
    ).astype("int8")
    return result
