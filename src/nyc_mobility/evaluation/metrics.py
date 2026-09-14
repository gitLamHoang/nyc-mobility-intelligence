"""Metrics use equal weight per zone-hour; SMAPE is in percent."""

import numpy as np
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score


def metrics(actual, predicted) -> dict[str, float | None]:
    actual, predicted = np.asarray(actual, dtype=float), np.asarray(predicted, dtype=float)
    if actual.ndim != 1 or actual.shape != predicted.shape or not actual.size:
        raise ValueError("Metric inputs must be nonempty, matching one-dimensional arrays")
    if not np.isfinite(actual).all() or not np.isfinite(predicted).all():
        raise ValueError("Metric inputs must be finite")
    denominator = np.abs(actual) + np.abs(predicted)
    smape = np.divide(
        200 * np.abs(actual - predicted),
        denominator,
        out=np.zeros_like(actual),
        where=denominator != 0,
    ).mean()
    return {
        "mae": float(mean_absolute_error(actual, predicted)),
        "rmse": float(np.sqrt(mean_squared_error(actual, predicted))),
        "r2": float(r2_score(actual, predicted)) if actual.size > 1 else None,
        "smape_pct": float(smape),
    }
