"""Artificial fixtures test leakage/coverage contracts, never performance evidence."""

import copy
import hashlib
import json
import tomllib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from xgboost import DMatrix

from nyc_mobility.config import load_config, write_json
from nyc_mobility.data.download import sha256
from nyc_mobility.evaluation.backtest import pooled_scores
from nyc_mobility.evaluation.metrics import metrics
from nyc_mobility.evaluation.splits import expanding_folds, local_boundary
from nyc_mobility.evaluation.xgboost import CONTROL_NAMES, run_xgboost, validate_protocol
from nyc_mobility.features.temporal import FEATURES, make_features
from nyc_mobility.models.xgboost import xgboost_estimator


def protocol():
    return tomllib.loads(Path("configs/xgboost.toml").read_text())


@pytest.mark.parametrize("change", ["test_boundary", "depth", "fits", "trees", "early_stop"])
def test_protocol_rejects_test_overlap_and_budget_expansion(change):
    spec = protocol()
    if change == "test_boundary":
        spec["study"]["validation_boundaries"][-1] = "2026-06-01"
    elif change == "depth":
        spec["study"]["max_depths"].append(8)
    elif change == "fits":
        spec["study"]["fit_budget"] = 9
    elif change == "trees":
        spec["model"]["n_estimators"] = 1000
    else:
        spec["model"]["early_stopping_rounds"] = 10
    with pytest.raises(ValueError):
        validate_protocol(spec, load_config())


def test_dense_encoding_keeps_zeros_and_refuses_unknown_zones():
    model = xgboost_estimator(protocol()["model"], 4)
    values = pd.DataFrame(0.0, index=range(12), columns=FEATURES)
    values["zone_id"] = [2, 3] * 6
    model.fit(values, np.arange(12, dtype=float))
    encoded = model[:-1].transform(values)
    assert isinstance(encoded, np.ndarray)
    assert encoded.dtype == np.float32
    assert encoded.shape == (12, 19)
    assert np.count_nonzero(encoded) == 12
    matrix = DMatrix(encoded, missing=np.nan)
    assert matrix.num_nonmissing() == encoded.size
    assert np.isfinite(model.predict(values)).all()
    assert model[-1].get_booster().num_boosted_rounds() == 120
    values.loc[0, "zone_id"] = 99
    with pytest.raises(ValueError, match="unknown categories"):
        model.predict(values)


def write_protocol(path, spec):
    lines = []
    for section in ["study", "control", "control.prediction_sha256", "model"]:
        values = spec["control"]["prediction_sha256"] if "." in section else spec[section]
        lines.append(f"[{section}]")
        lines.extend(f"{k} = {json.dumps(v)}" for k, v in values.items() if not isinstance(v, dict))
    path.write_text("\n".join(lines) + "\n")


@pytest.fixture
def comparison_fixture(tmp_path):
    spec = protocol()
    study = spec["study"]
    study.update(
        train_start="2026-01-01",
        sealed_test_start="2026-01-13",
        validation_boundaries=["2026-01-10", "2026-01-11", "2026-01-12", "2026-01-13"],
    )
    config = {
        "split": {"train_start": study["train_start"], "test_start": study["sealed_test_start"]}
    }
    hours = pd.date_range(
        local_boundary("2026-01-01"), local_boundary("2026-01-14"), inclusive="left", freq="h"
    )
    panel = pd.MultiIndex.from_product([[2, 3], hours], names=["zone_id", "hour"]).to_frame(
        index=False
    )
    panel["demand"] = np.where(panel.zone_id.eq(2), 0.0, 10.0)
    panel.loc[(panel.hour >= local_boundary("2026-01-10")) & panel.zone_id.eq(2), "demand"] = 100
    panel["borough"] = panel.zone_id.map({2: "Queens", 3: "Bronx"})
    panel["Zone"] = panel.zone_id.map({2: "A", 3: "B"})
    # These invalid labels must never reach feature construction.
    panel.loc[panel.hour >= local_boundary(study["sealed_test_start"]), "demand"] = np.nan
    data = tmp_path / "data/processed/hourly_demand.parquet"
    data.parent.mkdir(parents=True)
    panel.to_parquet(data, index=False)
    zones = tmp_path / "data/external/taxi_zone_lookup.csv"
    zones.parent.mkdir()
    pd.DataFrame({"LocationID": [2, 3], "Borough": ["Queens", "Bronx"], "Zone": ["A", "B"]}).to_csv(
        zones, index=False
    )
    spec["control"]["data_sha256"] = sha256(data)
    spec["control"]["latency_id"] = "artificial-control"
    features = make_features(
        panel.loc[panel.hour < local_boundary(study["sealed_test_start"])]
    ).dropna(subset=FEATURES)
    details = []
    artifact_dir = tmp_path / "artifacts/latency/artificial-control"
    artifact_dir.mkdir(parents=True)
    for fold in expanding_folds(
        study["train_start"], study["validation_boundaries"], study["sealed_test_start"]
    ):
        start, end = (
            fold.train_start + pd.Timedelta(hours=174),
            fold.validation_start - pd.Timedelta(hours=6),
        )
        train = features.loc[(features.hour >= start) & (features.hour < end)]
        valid = features.loc[
            (features.hour >= fold.validation_start) & (features.hour < fold.validation_end)
        ]
        sparse = train.groupby("zone_id").demand.mean().loc[lambda v: v <= 1].index.tolist()
        result = valid[
            ["zone_id", "hour", "demand", "borough", "local_hour", "weekend", "rush_hour"]
        ].copy()
        result["fold"] = fold.name
        result["zone_cohort"] = np.where(valid.zone_id.isin(sparse), "sparse", "dense")
        result["target_cohort"] = np.where(valid.demand.eq(0), "zero", "positive")
        for name in CONTROL_NAMES:
            result[name] = valid.lag_1.to_numpy()
        saved_path = artifact_dir / f"delay_0_{fold.name}.parquet"
        result.to_parquet(saved_path, index=False)
        spec["control"]["prediction_sha256"][fold.name] = sha256(saved_path)
        details.append(
            {
                "name": fold.name,
                "delay_hours": 0,
                "effective_train_start": start,
                "effective_train_end_exclusive": end,
                "training_max_target": train.hour.max(),
                "validation_start": fold.validation_start,
                "validation_end": fold.validation_end,
                "validation_rows": len(valid),
                "train_rows": len(train),
                "sparse_zone_ids": sparse,
                "training_targets_sha256": hashlib.sha256(
                    pd.util.hash_pandas_object(train[["zone_id", "hour", "demand"]], index=False)
                    .to_numpy()
                    .tobytes()
                ).hexdigest(),
                "metrics": {name: metrics(result.demand, result[name]) for name in CONTROL_NAMES},
            }
        )
    feature_source = "src/nyc_mobility/features/temporal.py"
    (tmp_path / feature_source).parent.mkdir(parents=True)
    (tmp_path / feature_source).write_bytes(Path(feature_source).read_bytes())
    report = tmp_path / "reports/latency/artificial-control/metrics.json"
    write_json(
        report,
        {
            "data_sha256": sha256(data),
            "features": FEATURES,
            "source_hashes": {feature_source: sha256(tmp_path / feature_source)},
            "protocol": {"study": copy.deepcopy(study)},
            "folds": details,
        },
    )
    spec["control"]["metrics_sha256"] = sha256(report)
    write_protocol(tmp_path / "study.toml", spec)
    (tmp_path / "uv.lock").write_text("artificial lock")
    (tmp_path / "artifacts/model.joblib").write_bytes(b"preserve serving model")
    (tmp_path / "reports/latest_latency.json").write_text("preserve control report")
    return config, spec, report


def recording_factory(monkeypatch):
    import nyc_mobility.evaluation.xgboost as module

    fits = []

    class RecordingModel:
        def fit(self, x, y):
            fits.append((self, x.copy(), y.copy()))
            self.value = float(y.mean())
            return self

        def predict(self, x):
            return np.full(len(x), self.value)

        def get_params(self):
            return {"strategy": "artificial-fixture-only"}

    monkeypatch.setattr(module, "xgboost_estimator", lambda params, depth: RecordingModel())
    return fits


def test_study_refits_six_times_excludes_test_and_preserves_controls(
    comparison_fixture, tmp_path, monkeypatch
):
    config, spec, _ = comparison_fixture
    fits = recording_factory(monkeypatch)
    record = run_xgboost(config, tmp_path, Path("study.toml"))
    assert len(fits) == record["models_fitted"] == 6
    assert len({id(item[0]) for item in fits}) == 6
    assert len(fits[0][2]) == 72
    assert fits[0][2].max() == 10
    assert fits[-1][2].max() == 100
    assert list(fits[0][1]) == FEATURES
    assert record["folds"][0]["sparse_zone_ids"] == [2]
    assert record["folds"][1]["sparse_zone_ids"] == []
    assert record["control_models_refitted"] == 0
    assert record["test_metrics"] is None
    assert record["validation_rows"] == 144
    assert (tmp_path / "artifacts/model.joblib").read_bytes() == b"preserve serving model"
    assert (tmp_path / "reports/latest_latency.json").read_text() == "preserve control report"
    output = tmp_path / "artifacts/xgboost" / record["xgboost_id"]
    predictions = pd.concat([pd.read_parquet(p) for p in sorted(output.glob("*.parquet"))])
    assert predictions.hour.max() < local_boundary(spec["study"]["sealed_test_start"])
    assert pooled_scores(predictions, list(record["pooled_metrics"])) == record["pooled_metrics"]


@pytest.mark.parametrize("defect", ["missing", "hash", "labels", "training", "cohort", "metric"])
def test_invalid_control_fails_before_any_fit(defect, comparison_fixture, tmp_path, monkeypatch):
    config, spec, report = comparison_fixture
    fits = recording_factory(monkeypatch)
    saved = tmp_path / "artifacts/latency/artificial-control/delay_0_fold_3.parquet"
    if defect == "missing":
        saved.unlink()
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
    write_protocol(tmp_path / "study.toml", spec)
    with pytest.raises(ValueError):
        run_xgboost(config, tmp_path, Path("study.toml"))
    assert fits == []
