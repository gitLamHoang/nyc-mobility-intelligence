import numpy as np
import pandas as pd
import pytest

from nyc_mobility.features.temporal import FEATURES, make_features


def test_lags_and_rolling_are_zone_local_and_strictly_past(panel):
    frame = make_features(panel)
    second = frame[frame.zone_id == 3].iloc[168]
    assert second.lag_1 == 1167
    assert second.lag_168 == 1000
    assert second.rolling_mean_3 == 1166
    assert second.rolling_std_24 == pytest.approx(np.std(np.arange(1144, 1168)))
    assert frame.loc[frame.zone_id == 3, "lag_1"].iloc[0] != frame.iloc[239].demand


def test_perturbing_present_and_future_cannot_change_features(panel):
    cutoff = panel.hour.iloc[200]
    before = make_features(panel)
    modified = panel.copy()
    modified.loc[modified.hour >= cutoff, "demand"] += 100000
    after = make_features(modified)
    pd.testing.assert_frame_equal(
        before.loc[before.hour <= cutoff, FEATURES], after.loc[after.hour <= cutoff, FEATURES]
    )


def test_row_order_does_not_change_results(panel):
    pd.testing.assert_frame_equal(
        make_features(panel), make_features(panel.sample(frac=1, random_state=2))
    )


@pytest.mark.parametrize(
    "fault", ["duplicate", "gap", "negative", "missing", "naive", "zone", "fraction"]
)
def test_invalid_panel_fails(panel, fault):
    if fault == "duplicate":
        panel = pd.concat([panel, panel.iloc[[0]]])
    elif fault == "gap":
        panel = panel.drop(index=3)
    elif fault == "negative":
        panel.loc[3, "demand"] = -1
    elif fault == "missing":
        panel.loc[3, "demand"] = np.nan
    elif fault == "naive":
        panel["hour"] = panel.hour.dt.tz_localize(None)
    elif fault == "zone":
        panel.loc[panel.zone_id == 2, "zone_id"] = 264
    elif fault == "fraction":
        panel["demand"] = panel.demand.astype(float)
        panel.loc[3, "demand"] = 0.5
    with pytest.raises(ValueError):
        make_features(panel)


def test_inference_features_match_training(panel):
    observed = make_features(panel)
    final = panel.groupby("zone_id").tail(1).index
    inference = panel.copy()
    inference.loc[final, "demand"] = np.nan
    transformed = make_features(inference, allow_future_target=True)
    pd.testing.assert_frame_equal(observed.loc[final, FEATURES], transformed.loc[final, FEATURES])


def test_inference_rejects_holes_in_observed_history(panel):
    panel.loc[10, "demand"] = np.nan
    with pytest.raises(ValueError, match="final target"):
        make_features(panel, allow_future_target=True)
