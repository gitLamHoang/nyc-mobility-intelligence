"""Artificial fixtures verify the protocol; they are not project performance evidence."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from nyc_mobility.config import load_config
from nyc_mobility.evaluation.backtest import (
    pooled_scores,
    run_backtest,
    study_estimators,
)
from nyc_mobility.evaluation.metrics import metrics
from nyc_mobility.evaluation.splits import (
    expanding_folds,
    local_boundary,
    require_complete_window,
)


def test_folds_are_expanding_nonoverlapping_and_dst_aware():
    folds = expanding_folds(
        "2025-12-01", ["2026-02-01", "2026-03-01", "2026-04-01", "2026-05-01"], "2026-05-01"
    )
    assert len(folds) == 3
    assert len({fold.train_start for fold in folds}) == 1
    assert folds[0].validation_end == folds[1].validation_start
    assert folds[1].validation_end == folds[2].validation_start
    assert folds[-1].validation_end == pd.Timestamp("2026-05-01 04:00Z")
    march = folds[1]
    assert (march.validation_end - march.validation_start).total_seconds() / 3600 == 743


@pytest.mark.parametrize(
    "boundaries",
    [
        ["2026-02-01"],
        ["2026-03-01", "2026-02-01"],
        ["2026-02-01", "2026-02-01"],
        ["2026-04-01", "2026-06-01"],
        ["2025-11-01", "2026-02-01"],
    ],
)
def test_invalid_or_test_overlapping_folds_are_rejected(boundaries):
    with pytest.raises(ValueError):
        expanding_folds("2025-12-01", boundaries, "2026-05-01")


@pytest.mark.parametrize("defect", ["missing_hour", "missing_zone", "duplicate", "misaligned"])
def test_equal_forecast_coverage_is_enforced(defect):
    start, stop = local_boundary("2026-03-08"), local_boundary("2026-03-09")
    hours = pd.date_range(start, stop, inclusive="left", freq="h")
    frame = pd.MultiIndex.from_product([[2, 3], hours], names=["zone_id", "hour"]).to_frame(
        index=False
    )
    require_complete_window(frame, [2, 3], start, stop)
    if defect == "missing_hour":
        frame = frame.drop(index=5)
    elif defect == "missing_zone":
        frame = frame.loc[frame.zone_id == 2]
    elif defect == "duplicate":
        frame = pd.concat([frame, frame.iloc[[0]]])
    else:
        frame["hour"] += pd.Timedelta(minutes=30)
    with pytest.raises(ValueError):
        require_complete_window(frame, [2, 3], start, stop)


def test_pooled_metrics_use_all_errors_not_mean_fold_rmse():
    frame = pd.DataFrame(
        {
            "zone_id": [2, 2, 2],
            "hour": pd.date_range("2026-02-01", periods=3, freq="h", tz="UTC"),
            "demand": [0, 10, 20],
            "candidate": [0, 7, 16],
        }
    )
    score = pooled_scores(frame, ["candidate"])["candidate"]
    assert score["mae"] == pytest.approx(7 / 3)
    assert score["rmse"] == pytest.approx(np.sqrt(25 / 3))
    wrong_average = (0 + np.sqrt(25 / 2)) / 2
    assert score["rmse"] != pytest.approx(wrong_average)
    with pytest.raises(ValueError, match="overlap"):
        pooled_scores(pd.concat([frame, frame.iloc[[0]]]), ["candidate"])


def test_constant_target_r2_is_undefined():
    assert metrics([0, 0], [0, 0])["r2"] is None
    assert metrics([5, 5], [4, 7])["r2"] is None
    assert metrics([0, 1], [0, 1])["r2"] == 1


def test_estimator_settings_and_preprocessors_are_independent():
    names = [
        "hist_gradient_boosting",
        "hist_gradient_boosting_poisson",
        "hist_gradient_boosting_absolute",
    ]
    candidates = study_estimators(load_config()["model"], names)
    next_fold = study_estimators(load_config()["model"], names)
    for name, loss in zip(names, ["squared_error", "poisson", "absolute_error"], strict=True):
        assert candidates[name][-1].loss == loss
        assert candidates[name][-1].early_stopping is False
        assert candidates[name][-1].max_iter == 120
        assert candidates[name][0] is not next_fold[name][0]
    assert candidates[names[0]][0] is not candidates[names[1]][0]
    with pytest.raises(ValueError):
        study_estimators(load_config()["model"], ["unknown"])


def test_backtest_excludes_test_labels_refits_and_preserves_serving_state(tmp_path, monkeypatch):
    import nyc_mobility.evaluation.backtest as module

    start, end = local_boundary("2026-01-01"), local_boundary("2026-01-16")
    hours = pd.date_range(start, end, freq="h", inclusive="left")
    panel = pd.MultiIndex.from_product([[2, 3], hours], names=["zone_id", "hour"]).to_frame(
        index=False
    )
    panel["demand"] = np.where(panel.zone_id.eq(2), 0.0, 10.0)
    panel.loc[(panel.zone_id == 2) & (panel.hour >= local_boundary("2026-01-10")), "demand"] = 100.0
    panel["borough"] = np.where(panel.zone_id.eq(2), "Queens", "Bronx")
    panel["Zone"] = panel.zone_id.map({2: "A", 3: "B"})
    # Invalid held-out labels would fail feature validation if accidentally loaded.
    panel.loc[panel.hour >= local_boundary("2026-01-14"), "demand"] = np.nan
    data = tmp_path / "data/processed"
    data.mkdir(parents=True)
    panel.to_parquet(data / "hourly_demand.parquet", index=False)
    external = tmp_path / "data/external"
    external.mkdir()
    pd.DataFrame({"LocationID": [2, 3], "Borough": ["Queens", "Bronx"], "Zone": ["A", "B"]}).to_csv(
        external / "taxi_zone_lookup.csv", index=False
    )
    protocol = tmp_path / "study.toml"
    protocol.write_text("""[study]
id = "unit-test-only"
train_start = "2026-01-01"
validation_boundaries = ["2026-01-10", "2026-01-12", "2026-01-14"]
sealed_test_start = "2026-01-14"
feature_set = "temporal-v1"
primary_metric = "pooled_mae"
sparse_zone_mean_max = 1.0
models = ["test_mean"]
[model]
random_seed = 42
""")
    (tmp_path / "uv.lock").write_text("unit-test-only lock")
    serving = tmp_path / "artifacts/model.joblib"
    serving.parent.mkdir()
    serving.write_bytes(b"do not replace")
    old_report = tmp_path / "reports/latest_experiment.json"
    old_report.parent.mkdir()
    old_report.write_text('{"test_metrics": null}')
    config = {"split": {"train_start": "2026-01-01", "test_start": "2026-01-14"}}
    fits = []

    class RecordingMean:
        def fit(self, x, y):
            self.value = float(y.mean())
            fits.append({"instance": self, "targets": y.copy(), "columns": list(x.columns)})
            return self

        def predict(self, x):
            return np.full(len(x), self.value)

        def get_params(self):
            return {"strategy": "unit-test-only mean"}

    monkeypatch.setattr(
        module, "study_estimators", lambda config, names: {"test_mean": RecordingMean()}
    )
    record = run_backtest(config, tmp_path, Path("study.toml"))
    assert len(fits) == 2
    assert fits[0]["instance"] is not fits[1]["instance"]
    assert len(fits[0]["targets"]) == 96
    assert len(fits[1]["targets"]) == 192
    assert fits[0]["targets"].max() == 10
    assert fits[1]["targets"].max() == 100
    assert "demand" not in fits[0]["columns"]
    assert record["validation_rows"] == 192
    assert record["folds"][0]["sparse_zone_ids"] == [2]
    assert record["folds"][1]["sparse_zone_ids"] == []
    assert record["test_metrics"] is None
    assert record["serving_model_changed"] is False
    assert serving.read_bytes() == b"do not replace"
    assert old_report.read_text() == '{"test_metrics": null}'
    saved = json.loads((tmp_path / "reports/latest_backtest.json").read_text())
    assert saved["backtest_id"] == record["backtest_id"]
    predictions = pd.concat(
        [
            pd.read_parquet(p)
            for p in (tmp_path / "artifacts/backtests" / record["backtest_id"]).glob("*.parquet")
        ]
    )
    assert predictions.hour.max() < local_boundary("2026-01-14")
    assert not predictions.duplicated(["zone_id", "hour"]).any()
