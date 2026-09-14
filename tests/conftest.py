"""Small deterministic fixtures are unit-test inputs, never reported project data."""

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def panel():
    hours = pd.date_range("2026-01-01", periods=240, freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "zone_id": np.repeat([2, 3], len(hours)),
            "hour": list(hours) * 2,
            "demand": np.concatenate([np.arange(len(hours)), np.arange(len(hours)) + 1000]),
        }
    )
