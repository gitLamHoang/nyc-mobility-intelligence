"""Artificial fixtures verify the budget, matched controls and training-only preprocessing."""

import json
import tomllib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sklearn.base import BaseEstimator, RegressorMixin
from test_xgboost import comparison_fixture as comparison_fixture

from nyc_mobility.config import load_config, write_json
from nyc_mobility.data.download import sha256
from nyc_mobility.evaluation.backtest import pooled_scores
from nyc_mobility.evaluation.borough import run_borough, validate_protocol
from nyc_mobility.evaluation.splits import local_boundary
from nyc_mobility.features.borough import STATIC_FEATURES
from nyc_mobility.features.temporal import FEATURES
from nyc_mobility.models.borough import BUNDLES, borough_estimator
from nyc_mobility.models.train import estimators


def protocol():
    return tomllib.loads(Path("configs/borough_spatial.toml").read_text())


def write_protocol(path, spec):
    lines = []
    for section in ["study", "features", "control", "control.prediction_sha256", "model"]:
        values = spec["control"]["prediction_sha256"] if "." in section else spec[section]
        lines.append(f"[{section}]")
        lines.extend(f"{k} = {json.dumps(v)}" for k, v in values.items() if not isinstance(v, dict))
    path.write_text("\n".join(lines) + "\n")


@pytest.mark.parametrize(
    "change",
    [
        "may",
        "bundle",
        "budget",
        "trees",
        "loss",
        "early_stop",
        "columns",
        "polygon",
        "availability",
        "delay",
        "boolean_delay",
    ],
)
def test_borough_protocol_rejects_changed_budget_features_or_availability(change):
    spec = protocol()
    if change == "may":
        spec["study"]["validation_boundaries"][-1] = "2026-06-01"
    elif change == "bundle":
        spec["study"]["bundles"].append("geometry")
    elif change == "budget":
        spec["study"]["fit_budget"] = 8
    elif change == "trees":
        spec["model"]["boosting_iterations"] = 1000
    elif change == "loss":
        spec["model"]["loss"] = "poisson"
    elif change == "early_stop":
        spec["model"]["early_stopping"] = True
    elif change == "columns":
        spec["features"]["static"].append("borough_other_count")
    elif change == "polygon":
        spec["features"]["polygon_features_eligible"] = True
    elif change == "availability":
        spec["features"]["lookup_available_at"] = "2026-02-01T00:00Z"
    else:
        spec["study"]["observation_delay_hours"] = False if change == "boolean_delay" else 1
    with pytest.raises(ValueError):
        validate_protocol(spec, load_config())


@pytest.mark.parametrize("bundle", list(BUNDLES))
def test_borough_encoding_preserves_control_matrix_and_only_appends_declared_columns(bundle):
    spec = protocol()
    base = estimators(spec["model"])["hist_gradient_boosting"]
    model = borough_estimator(spec["model"], bundle)
    frame = pd.DataFrame(0.0, index=range(6), columns=BUNDLES[bundle])
    frame["zone_id"] = [2, 3] * 3
    frame["lag_1"] = np.arange(6, dtype=float)
    frame[STATIC_FEATURES[0]] = 1
    a = base[0].fit_transform(frame[FEATURES])
    b = model[0].fit_transform(frame)
    np.testing.assert_array_equal(a, b[:, : a.shape[1]])
    np.testing.assert_array_equal(b[:, a.shape[1] :], frame[BUNDLES[bundle][len(FEATURES) :]])
    assert a.dtype == b.dtype == np.float64
    assert base[-1].get_params() == model[-1].get_params()
    assert not model[-1].early_stopping
    assert "borough_other_count" not in model[0].get_feature_names_out()
    assert base[0] is not model[0]


@pytest.fixture
def borough_fixture(comparison_fixture, tmp_path):
    config, original, report = comparison_fixture
    spec = protocol()
    for key in ["train_start", "sealed_test_start", "validation_boundaries"]:
        spec["study"][key] = original["study"][key]
    spec["control"] = original["control"]
    spec["features"]["lookup_sha256"] = sha256(tmp_path / "data/external/taxi_zone_lookup.csv")
    source = "src/nyc_mobility/features/borough.py"
    (tmp_path / source).write_bytes(Path(source).read_bytes())
    spec["features"]["borough_source_sha256"] = sha256(tmp_path / source)
    write_protocol(tmp_path / "borough.toml", spec)
    return config, spec, report


def recording_factory(monkeypatch, mutation=None):
    import nyc_mobility.evaluation.borough as module

    fits, pipelines = [], []

    class RecordingRegressor(RegressorMixin, BaseEstimator):
        def fit(self, x, y):
            fits.append((self, x.copy(), y.copy()))
            self.value_ = float(y.mean())
            if mutation and len(fits) == 1:
                mutation()
            return self

        def predict(self, x):
            return np.full(len(x), self.value_)

    def factory(config, bundle):
        pipeline = borough_estimator(config, bundle)
        pipeline.steps[-1] = ("histgradientboostingregressor", RecordingRegressor())
        pipelines.append(pipeline)
        return pipeline

    monkeypatch.setattr(module, "borough_estimator", factory)
    return fits, pipelines


def test_borough_study_has_six_fresh_fits_matched_targets_and_sealed_test(
    borough_fixture, tmp_path, monkeypatch
):
    config, spec, _ = borough_fixture
    fits, pipelines = recording_factory(monkeypatch)
    record = run_borough(config, tmp_path, Path("borough.toml"))
    assert len(fits) == record["models_fitted"] == 6
    assert len({id(p[0]) for p in pipelines}) == 6
    assert len({id(f[0]) for f in fits}) == 6
    assert len(fits[0][2]) == len(fits[1][2]) == 72
    assert fits[0][2].max() == 10 and fits[-1][2].max() == 100
    for i, model in enumerate(pipelines):
        name = spec["study"]["bundles"][i % 2]
        assert list(model.feature_names_in_) == BUNDLES[name]
        representation = record["folds"][i // 2]["representations"][name]
        assert representation["input_columns"] == BUNDLES[name]
        assert representation["transformed_width"] == fits[i][1].shape[1]
        assert representation["transformed_dtype"] == str(fits[i][1].dtype)
    assert record["folds"][0]["sparse_zone_ids"] == [2]
    assert record["folds"][1]["sparse_zone_ids"] == []
    assert record["control_models_refitted"] == 0
    assert record["temporal_columns_identical"] is True
    assert record["test_metrics"] is None
    assert record["validation_rows"] == 144
    output = tmp_path / "artifacts/borough" / record["borough_id"]
    predictions = pd.concat([pd.read_parquet(p) for p in sorted(output.glob("*.parquet"))])
    assert predictions.hour.max() < local_boundary(spec["study"]["sealed_test_start"])
    assert pooled_scores(predictions, list(record["pooled_metrics"])) == record["pooled_metrics"]
    assert (tmp_path / "artifacts/model.joblib").read_bytes() == b"preserve serving model"
    assert (tmp_path / "reports/latest_latency.json").read_text() == "preserve control report"
    assert not (tmp_path / "reports/latest_xgboost.json").exists()


@pytest.mark.parametrize(
    "defect",
    [
        "missing",
        "hash",
        "labels",
        "training",
        "cohort",
        "metric",
        "lookup",
        "feature_source",
    ],
)
def test_borough_rejects_invalid_last_control_and_sources_before_fitting(
    defect, borough_fixture, tmp_path, monkeypatch
):
    config, spec, report = borough_fixture
    fits, _ = recording_factory(monkeypatch)
    saved = tmp_path / "artifacts/latency/artificial-control/delay_0_fold_3.parquet"
    if defect == "missing":
        saved.unlink()
    elif defect in ["lookup", "feature_source"]:
        name = (
            "data/external/taxi_zone_lookup.csv"
            if defect == "lookup"
            else "src/nyc_mobility/features/borough.py"
        )
        with (tmp_path / name).open("a") as f:
            f.write("\n")
    elif defect in ["hash", "labels", "cohort"]:
        frame = pd.read_parquet(saved)
        frame.loc[0, "zone_cohort" if defect == "cohort" else "demand"] = (
            "sparse" if defect == "cohort" else 999
        )
        frame.to_parquet(saved, index=False)
        if defect != "hash":
            spec["control"]["prediction_sha256"]["fold_3"] = sha256(saved)
    else:
        contents = json.loads(report.read_text())
        if defect == "training":
            contents["folds"][-1]["training_targets_sha256"] = "invalid"
        else:
            contents["folds"][-1]["metrics"]["hist_gradient_boosting"]["mae"] = 999
        write_json(report, contents)
        spec["control"]["metrics_sha256"] = sha256(report)
    write_protocol(tmp_path / "borough.toml", spec)
    with pytest.raises(ValueError):
        run_borough(config, tmp_path, Path("borough.toml"))
    assert fits == []


def test_borough_refuses_to_publish_if_frozen_source_changes_during_fit(
    borough_fixture, tmp_path, monkeypatch
):
    config, _, _ = borough_fixture

    def mutation():
        with (tmp_path / "src/nyc_mobility/features/borough.py").open("a") as f:
            f.write("\n")

    recording_factory(monkeypatch, mutation)
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        run_borough(config, tmp_path, Path("borough.toml"))
    assert not (tmp_path / "reports/latest_borough.json").exists()
