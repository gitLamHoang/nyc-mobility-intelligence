"""All split boundaries are local NYC midnights; intervals are half-open."""

from dataclasses import dataclass

import pandas as pd

from nyc_mobility.config import TIMEZONE


def local_boundary(value: str) -> pd.Timestamp:
    return pd.Timestamp(value, tz=TIMEZONE).tz_convert("UTC")


@dataclass(frozen=True)
class ForecastFold:
    name: str
    train_start: pd.Timestamp
    validation_start: pd.Timestamp
    validation_end: pd.Timestamp


def expanding_folds(
    train_start: str, validation_boundaries: list[str], test_start: str
) -> list[ForecastFold]:
    """Create nonoverlapping validation folds with a fixed expanding training origin."""
    start, test = local_boundary(train_start), local_boundary(test_start)
    boundaries = [local_boundary(value) for value in validation_boundaries]
    if len(boundaries) < 2 or not start < boundaries[0]:
        raise ValueError("At least one validation interval after training start is required")
    if any(left >= right for left, right in zip(boundaries[:-1], boundaries[1:], strict=True)):
        raise ValueError("Validation boundaries must be strictly increasing")
    if boundaries[-1] > test:
        raise ValueError("Validation cannot include held-out test targets")
    if any(value != value.floor("h") for value in [start, *boundaries, test]):
        raise ValueError("Fold boundaries must align to hours")
    return [
        ForecastFold(f"fold_{index + 1}", start, left, right)
        for index, (left, right) in enumerate(zip(boundaries[:-1], boundaries[1:], strict=True))
    ]


def require_complete_window(
    frame: pd.DataFrame, zone_ids: list[int], start: pd.Timestamp, stop: pd.Timestamp
) -> None:
    """Fail on missing zones/hours, duplicates, misaligned times or unequal coverage."""
    expected_hours = len(pd.date_range(start, stop, freq="h", inclusive="left"))
    if expected_hours == 0 or frame.empty or frame.duplicated(["zone_id", "hour"]).any():
        raise ValueError("Forecast window must be nonempty without duplicate zone-hours")
    if not isinstance(frame.hour.dtype, pd.DatetimeTZDtype) or frame.hour.isna().any():
        raise ValueError("Forecast targets require nonmissing timezone-aware timestamps")
    if not frame.hour.eq(frame.hour.dt.floor("h")).all():
        raise ValueError("Forecast targets must be aligned to hours")
    coverage = frame.groupby("zone_id").hour.agg(["min", "max", "count"])
    if (
        set(coverage.index) != set(zone_ids)
        or not coverage["count"].eq(expected_hours).all()
        or not coverage["min"].eq(start).all()
        or not coverage["max"].eq(stop - pd.Timedelta(hours=1)).all()
    ):
        raise ValueError("Incomplete or out-of-range zone/hour forecast coverage")


def chronological_split(frame: pd.DataFrame, split: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return development partitions only. Test labels are deliberately not returned."""
    start, validation, test, end = [
        local_boundary(split[key])
        for key in ("train_start", "validation_start", "test_start", "test_end")
    ]
    if not start < validation < test < end:
        raise ValueError("Chronological boundaries must be strictly increasing")
    train = frame.loc[(frame.hour >= start) & (frame.hour < validation)].copy()
    valid = frame.loc[(frame.hour >= validation) & (frame.hour < test)].copy()
    if train.empty or valid.empty:
        raise ValueError("Empty training or validation partition")
    if train.hour.max() >= valid.hour.min():
        raise ValueError("Training and validation overlap")
    return train, valid
