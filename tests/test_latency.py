"""Artificial fixtures verify observation availability, not project performance."""

import json
import tomllib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from nyc_mobility.config import load_config
from nyc_mobility.evaluation.latency import delay_effects, run_latency, validate_protocol
from nyc_mobility.evaluation.splits import local_boundary
from nyc_mobility.features.temporal import FEATURES, effective_lags, make_features


@pytest.mark.parametrize("delay", [0, 1, 3, 6])
def test_delayed_features_match_available_history_and_preserve_seasonal_lags(panel, delay):
    panel["demand"] = (np.arange(len(panel)) ** 2 % 97).astype(float)
    actual = make_features(panel, observation_delay_hours=delay)
    history = panel.loc[panel.zone_id == 3, "demand"].to_numpy()
    row = actual.loc[actual.zone_id == 3].iloc[200]
    for name, offset in effective_lags(delay).items():
        assert row[name] == history[200 - offset]
    for width in [3, 24, 168]:
        assert row[f"rolling_mean_{width}"] == pytest.approx(
            history[200 - delay - width : 200 - delay].mean()
        )
    assert row.rolling_std_24 == pytest.approx(history[176 - delay : 200 - delay].std())
    assert row.trend_1 == history[199 - delay] - history[198 - delay]
    assert row.lag_24 == history[176] and row.lag_168 == history[32]


@pytest.mark.parametrize("delay", [0, 1, 3, 6])
def test_unavailable_tail_and_future_cannot_change_features(panel, delay):
    target = panel.hour.iloc[200]
    before = make_features(panel, observation_delay_hours=delay)
    perturbed = panel.copy()
    perturbed.loc[perturbed.hour >= target - pd.Timedelta(hours=delay), "demand"] += 100000
    after = make_features(perturbed, observation_delay_hours=delay)
    pd.testing.assert_frame_equal(
        before.loc[before.hour <= target, FEATURES], after.loc[after.hour <= target, FEATURES]
    )
    permitted = panel.copy()
    latest = target - pd.Timedelta(hours=delay + 1)
    permitted.loc[(permitted.zone_id == 2) & (permitted.hour == latest), "demand"] += 12
    changed = make_features(permitted, observation_delay_hours=delay)
    key = (before.zone_id == 2) & (before.hour == target)
    assert changed.loc[key, "lag_1"].iloc[0] - before.loc[key, "lag_1"].iloc[0] == 12
    assert (
        changed.loc[key, "rolling_mean_3"].iloc[0] - before.loc[key, "rolling_mean_3"].iloc[0] == 4
    )
    pd.testing.assert_frame_equal(
        before.loc[key, ["lag_24", "lag_168"]], changed.loc[key, ["lag_24", "lag_168"]]
    )


def test_target_calendar_stays_aligned_across_dst():
    panel = pd.DataFrame(
        {
            "zone_id": 2,
            "hour": pd.date_range("2026-03-01 05:00Z", periods=240, freq="h"),
            "demand": np.arange(240),
        }
    )
    original = make_features(panel)
    delayed = make_features(panel, observation_delay_hours=6)
    columns = [
        "hour",
        "local_hour",
        "weekday",
        "weekend",
        "month",
        "rush_hour",
        "hour_sin",
        "hour_cos",
        "weekday_sin",
        "weekday_cos",
    ]
    pd.testing.assert_frame_equal(original[columns], delayed[columns])
    assert delayed.loc[delayed.hour == pd.Timestamp("2026-03-08 07:00Z"), "local_hour"].iloc[0] == 3
    pd.testing.assert_frame_equal(original, make_features(panel, observation_delay_hours=0))


@pytest.mark.parametrize("delay", [-1, 2, 24, 1.5, True, "1"])
def test_unsupported_observation_delays_fail(panel, delay):
    with pytest.raises(ValueError, match="Supported observation delays"):
        make_features(panel, observation_delay_hours=delay)


@pytest.mark.parametrize(
    "field,value",
    [
        ("common_warmup_hours", 168),
        ("common_training_embargo_hours", 5),
        ("delay_hours", [0, 1, 2, 6]),
        ("sealed_test_start", "2026-06-01"),
    ],
)
def test_protocol_cannot_silently_relax_comparability(field, value):
    with Path("configs/latency.toml").open("rb") as stream:
        protocol = tomllib.load(stream)
    validate_protocol(protocol, load_config())
    protocol["study"][field] = value
    with pytest.raises(ValueError):
        validate_protocol(protocol, load_config())


def test_effects_use_scope_specific_zero_delay_and_handle_perfect_control():
    pooled = [{"delay_hours": d, "model": "m", "mae": v} for d, v in [(0, 2), (1, 3)]]
    folds = [{"delay_hours": d, "fold": "f", "model": "m", "mae": v} for d, v in [(0, 0), (1, 1)]]
    effects = delay_effects(pooled, folds, "m")
    assert (
        effects.loc[
            (effects.scope == "pooled") & (effects.delay_hours == 1), "mae_increase_pct"
        ].iloc[0]
        == 50
    )
    assert effects.loc[effects.scope == "f", "mae_increase_pct"].isna().all()


def test_latency_runner_matches_targets_refits_and_excludes_test(tmp_path, monkeypatch):
    import nyc_mobility.evaluation.backtest as module

    hours = pd.date_range(
        local_boundary("2026-01-01"), local_boundary("2026-01-16"), inclusive="left", freq="h"
    )
    panel = pd.MultiIndex.from_product([[2, 3], hours], names=["zone_id", "hour"]).to_frame(
        index=False
    )
    panel["demand"] = np.where(panel.zone_id.eq(2), 0.0, 10.0)
    panel.loc[(panel.zone_id == 2) & (panel.hour >= local_boundary("2026-01-10")), "demand"] = 100
    panel.loc[panel.hour >= local_boundary("2026-01-14"), "demand"] = np.nan
    panel["borough"] = np.where(panel.zone_id.eq(2), "Queens", "Bronx")
    panel["Zone"] = panel.zone_id.map({2: "A", 3: "B"})
    data = tmp_path / "data/processed/hourly_demand.parquet"
    data.parent.mkdir(parents=True)
    panel.to_parquet(data, index=False)
    external = tmp_path / "data/external"
    external.mkdir()
    pd.DataFrame({"LocationID": [2, 3], "Borough": ["Queens", "Bronx"], "Zone": ["A", "B"]}).to_csv(
        external / "taxi_zone_lookup.csv", index=False
    )
    raw_protocol = Path("configs/latency.toml").read_text()
    raw_protocol = (
        raw_protocol.replace('"2025-12-01"', '"2026-01-01"')
        .replace(
            '["2026-02-01", "2026-03-01", "2026-04-01", "2026-05-01"]',
            '["2026-01-10", "2026-01-12", "2026-01-14"]',
        )
        .replace('"2026-05-01"', '"2026-01-14"')
    )
    protocol = tmp_path / "latency.toml"
    protocol.write_text(raw_protocol)
    (tmp_path / "uv.lock").write_text("unit-test-only lock")
    preserved = [
        "artifacts/model.joblib",
        "reports/latest_experiment.json",
        "reports/latest_backtest.json",
        "reports/latest_uncertainty.json",
    ]
    for name in preserved:
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"unchanged")
    data_before = data.read_bytes()
    fits = []

    class RecordingMean:
        def fit(self, x, y):
            self.value = float(y.mean())
            fits.append((self, x.copy(), y.copy()))
            return self

        def predict(self, x):
            return np.full(len(x), self.value)

        def get_params(self):
            return {"strategy": "artificial mean for boundary test"}

    monkeypatch.setattr(
        module,
        "study_estimators",
        lambda config, names: {"hist_gradient_boosting": RecordingMean()},
    )
    config = {"split": {"train_start": "2026-01-01", "test_start": "2026-01-14"}}
    record = run_latency(config, tmp_path, protocol)
    assert len(fits) == record["models_fitted"] == 8
    assert len({id(instance) for instance, _, _ in fits}) == 8
    assert [len(y) for _, _, y in fits] == [72, 168] * 4
    assert record["validation_rows_per_setting"] == 192
    # The Parquet filter removes held-out rows before the feature builder resets its index.
    development = panel.loc[panel.hour < local_boundary("2026-01-14")].reset_index(drop=True)
    for index, (_, x, y) in enumerate(fits):
        cutoff = local_boundary("2026-01-10" if index % 2 == 0 else "2026-01-12")
        assert development.loc[y.index, "zone_id"].eq(x.zone_id).all()
        assert development.loc[y.index, "hour"].max() == cutoff - pd.Timedelta(hours=7)
        assert development.loc[y.index, "hour"].min() == local_boundary(
            "2026-01-01"
        ) + pd.Timedelta(hours=174)
        assert "demand" not in x.columns
    for fold in ["fold_1", "fold_2"]:
        entries = [r for r in record["folds"] if r["name"] == fold]
        assert len({r["training_targets_sha256"] for r in entries}) == 1
        assert all(
            pd.Timestamp(r["last_training_label_available_at"])
            <= pd.Timestamp(r["validation_start"])
            for r in entries
        )
        assert all(r["sparse_zone_ids"] == entries[0]["sparse_zone_ids"] for r in entries)
    directory = tmp_path / "artifacts/latency" / record["latency_id"]
    controls = {
        fold: pd.read_parquet(directory / f"delay_0_{fold}.parquet")
        for fold in ["fold_1", "fold_2"]
    }
    for delay in [0, 1, 3, 6]:
        for fold, control in controls.items():
            observed = pd.read_parquet(directory / f"delay_{delay}_{fold}.parquet")
            stable = [
                "zone_id",
                "hour",
                "demand",
                "zone_cohort",
                "previous_day_24h",
                "previous_week_168h",
                "zone_hour_average",
            ]
            pd.testing.assert_frame_equal(observed[stable], control[stable])
            assert observed.hour.max() < local_boundary("2026-01-14")
            assert "latest_available" in observed and "previous_hour" not in observed
    assert record["test_metrics"] is None and record["serving_model_changed"] is False
    assert data.read_bytes() == data_before
    assert all((tmp_path / name).read_bytes() == b"unchanged" for name in preserved)
    saved = json.loads((tmp_path / "reports/latest_latency.json").read_text())
    assert saved["models_fitted"] == 8 and saved["latency_id"] == record["latency_id"]
