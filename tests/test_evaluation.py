import numpy as np
import pandas as pd
import pytest

from nyc_mobility.evaluation.metrics import metrics
from nyc_mobility.evaluation.splits import chronological_split
from nyc_mobility.features.temporal import make_features
from nyc_mobility.models.baselines import baseline_predictions


def test_metrics_zero_safe_and_known_values():
    values = metrics([0, 2], [0, 0])
    assert values["mae"] == 1
    assert values["rmse"] == pytest.approx(np.sqrt(2))
    assert values["smape_pct"] == 100
    assert metrics([0, 0], [0, 0])["smape_pct"] == 0


@pytest.mark.parametrize("actual,predicted", [([], []), ([1], [1, 2]), ([np.nan], [1])])
def test_invalid_metrics(actual, predicted):
    with pytest.raises(ValueError):
        metrics(actual, predicted)


def test_split_boundary_is_new_york_midnight():
    frame = pd.DataFrame({"hour": pd.date_range("2026-03-31", "2026-05-02", freq="h", tz="UTC")})
    split = {
        "train_start": "2026-03-01",
        "validation_start": "2026-04-01",
        "test_start": "2026-05-01",
        "test_end": "2026-06-01",
    }
    train, valid = chronological_split(frame, split)
    assert train.hour.max() == pd.Timestamp("2026-04-01 03:00Z")
    assert valid.hour.min() == pd.Timestamp("2026-04-01 04:00Z")
    assert valid.hour.max() == pd.Timestamp("2026-05-01 03:00Z")
    with pytest.raises(ValueError):
        chronological_split(frame, {**split, "test_start": "2026-03-01"})


def test_baseline_averages_do_not_use_validation_labels(panel):
    featured = make_features(panel)
    train = featured.loc[featured.hour < panel.hour.iloc[200]]
    valid = featured.loc[featured.hour >= panel.hour.iloc[200]]
    before = baseline_predictions(train, valid)
    altered = valid.copy()
    altered["demand"] = 999999
    after = baseline_predictions(train, altered)
    assert len(before) == 5
    for key in before:
        np.testing.assert_array_equal(before[key], after[key])
