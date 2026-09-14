"""All split boundaries are local NYC midnights; intervals are half-open."""

import pandas as pd

from nyc_mobility.config import TIMEZONE


def local_boundary(value: str) -> pd.Timestamp:
    return pd.Timestamp(value, tz=TIMEZONE).tz_convert("UTC")


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
