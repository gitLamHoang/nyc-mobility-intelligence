"""Baselines fit historical averages on training data only."""

import pandas as pd


def baseline_predictions(train: pd.DataFrame, validation: pd.DataFrame) -> dict:
    averages = train.groupby(["zone_id", "local_hour"]).demand.mean()
    zone_means = train.groupby("zone_id").demand.mean()
    historical = validation[["zone_id", "local_hour"]].merge(
        averages.rename("prediction").reset_index(), on=["zone_id", "local_hour"], how="left"
    )["prediction"]
    historical = historical.fillna(pd.Series(validation.zone_id.map(zone_means).to_numpy()))
    if historical.isna().any():
        raise ValueError("Validation includes zones absent from training")
    return {
        "previous_hour": validation.lag_1.to_numpy(),
        "previous_day_24h": validation.lag_24.to_numpy(),
        "previous_week_168h": validation.lag_168.to_numpy(),
        "zone_hour_average": historical.to_numpy(),
        "rolling_mean_24h": validation.rolling_mean_24.to_numpy(),
    }
