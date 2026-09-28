"""Synthetic fixtures test the frozen fit budget and missing-weather target preservation."""

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
from nyc_mobility.evaluation.splits import local_boundary
from nyc_mobility.evaluation.weather import append_weather, run_weather, validate_protocol
from nyc_mobility.features.temporal import FEATURES
from nyc_mobility.features.weather import WEATHER_VALUES
from nyc_mobility.features.weather_bundle import WEATHER_BUNDLE_FEATURES, WEATHER_STATIONS
from nyc_mobility.models.train import estimators
from nyc_mobility.models.weather import BUNDLES, weather_estimator


def protocol():
    return tomllib.loads(Path("configs/weather_ablation.toml").read_text())


def write_protocol(path, spec):
    lines = []
    for section in ["study", "weather", "control", "control.prediction_sha256", "model"]:
        values = spec["control"]["prediction_sha256"] if "." in section else spec[section]
        lines.append(f"[{section}]")
        lines.extend(
            f"{key} = {json.dumps(value)}"
            for key, value in values.items()
            if not isinstance(value, dict)
        )
    path.write_text("\n".join(lines) + "\n")


@pytest.mark.parametrize(
    "section,key,value",
    [
        ("study", "weather_delays_hours", [0, 3, 6]),
        ("study", "primary_weather_delay_hours", 6),
        ("study", "fit_budget", 8),
        ("study", "observation_delay_hours", 1),
        ("study", "observation_delay_hours", False),
        ("study", "common_training_embargo_hours", 0),
        ("study", "common_warmup_hours", 168),
        ("study", "missing_weather", "drop weather gaps"),
        (
            "study",
            "validation_boundaries",
            ["2026-02-01", "2026-03-01", "2026-04-01", "2026-06-01"],
        ),
        ("model", "boosting_iterations", 121),
        ("model", "loss", "poisson"),
        ("model", "early_stopping", True),
        ("weather", "features", ["temperature"]),
    ],
)
def test_changed_budget_features_or_availability_fail(section, key, value):
    spec = protocol()
    spec[section][key] = value
    with pytest.raises(ValueError):
        validate_protocol(spec, load_config())


@pytest.mark.parametrize("bundle", list(BUNDLES))
def test_encoding_preserves_temporal_matrix_and_native_weather_nans(bundle):
    spec = protocol()
    base = estimators(spec["model"])["hist_gradient_boosting"]
    model = weather_estimator(spec["model"], bundle)
    frame = pd.DataFrame(0.0, index=range(6), columns=BUNDLES[bundle])
    frame["zone_id"] = [2, 3] * 3
    frame["lag_1"] = np.arange(6, dtype=float)
    frame[WEATHER_BUNDLE_FEATURES[0]] = np.nan
    a, b = base[0].fit_transform(frame[FEATURES]), model[0].fit_transform(frame)
    np.testing.assert_array_equal(a, b[:, : a.shape[1]])
    np.testing.assert_allclose(b[:, a.shape[1] :], frame[WEATHER_BUNDLE_FEATURES], equal_nan=True)
    assert b.dtype == a.dtype == np.float64
    assert model[-1].get_params() == base[-1].get_params()
    assert model[0] is not base[0]


@pytest.fixture
def weather_fixture(comparison_fixture, tmp_path):
    config, original, report = comparison_fixture
    spec = protocol()
    for key in ["train_start", "sealed_test_start", "validation_boundaries"]:
        spec["study"][key] = original["study"][key]
    spec["control"] = original["control"]
    start, stop = (
        local_boundary(spec["study"]["train_start"]),
        local_boundary(spec["study"]["sealed_test_start"]),
    )
    hours = pd.date_range(start, stop, freq="h", inclusive="left")
    snapshots = []
    for delay in [3, 6]:
        for station in WEATHER_STATIONS.values():
            frame = pd.DataFrame({"hour": hours, "station_id": station, "delay_hours": delay})
            frame["observed_at"] = hours - pd.Timedelta(delay + 1, unit="h")
            frame["assumed_available_at"] = hours - pd.Timedelta(1, unit="h")
            frame["age_hours"] = float(delay + 1)
            for column in WEATHER_VALUES:
                frame[column] = np.arange(len(hours), dtype=float) / 100
                frame[column + "_quality"] = "unverified"
                frame[column + "_source"] = "413"
            # A persistently missing weather feature must never remove a taxi target.
            if station == "USW00094728":
                frame["wind_speed_m_s"] = np.nan
                frame["wind_speed_m_s_quality"] = "missing"
            snapshots.append(frame)
    snapshot_path = tmp_path / "artifacts/weather_policy/synthetic/snapshots.parquet"
    snapshot_path.parent.mkdir(parents=True)
    pd.concat(snapshots, ignore_index=True).to_parquet(snapshot_path, index=False)
    spec["weather"].update(
        weather_id="synthetic",
        metrics_file="reports/weather_policy/synthetic/metrics.json",
        snapshots_file=str(snapshot_path.relative_to(tmp_path)),
        snapshots_sha256=sha256(snapshot_path),
        lookup_sha256=sha256(tmp_path / "data/external/taxi_zone_lookup.csv"),
    )
    for source, key in [
        ("src/nyc_mobility/features/weather_bundle.py", "bundle_source_sha256"),
        ("configs/weather_inputs.toml", "legacy_spec_sha256"),
        ("docs/WEATHER_SOURCE_POLICY.md", "legacy_policy_sha256"),
    ]:
        target = tmp_path / source
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(Path(source).read_bytes())
        spec["weather"][key] = sha256(target)
    metadata = {
        "weather_id": "synthetic",
        "policy": {
            "quality": "documented-sources-with-unverified-v1",
            "max_age_hours": 12,
            "delays_hours": [0, 1, 3, 6],
        },
        "window_start_utc": start,
        "window_end_utc_exclusive": stop,
        "test_metrics": None,
        "models_fitted": 0,
        "historical_publication_times_verified": False,
        "eligible_for_point_in_time_model_claim": False,
        "outputs_sha256": {spec["weather"]["snapshots_file"]: spec["weather"]["snapshots_sha256"]},
    }
    record_path = tmp_path / spec["weather"]["metrics_file"]
    write_json(record_path, metadata)
    spec["weather"]["metrics_sha256"] = sha256(record_path)
    write_protocol(tmp_path / "weather.toml", spec)
    return config, spec, report


def recording_factory(monkeypatch, action=None):
    import nyc_mobility.evaluation.weather as module

    fits, pipelines = [], []

    class RecordingRegressor(RegressorMixin, BaseEstimator):
        def fit(self, x, y):
            fits.append((self, x.copy(), y.copy()))
            self.value_ = float(y.mean())
            if action:
                action(len(fits))
            return self

        def predict(self, x):
            return np.full(len(x), self.value_)

    def factory(config, bundle):
        model = weather_estimator(config, bundle)
        model.steps[-1] = ("histgradientboostingregressor", RecordingRegressor())
        pipelines.append(model)
        return model

    monkeypatch.setattr(module, "weather_estimator", factory)
    return fits, pipelines


def test_six_fresh_fits_retain_missing_weather_and_preserve_sealed_targets(
    weather_fixture, tmp_path, monkeypatch
):
    config, spec, _ = weather_fixture
    fits, pipelines = recording_factory(monkeypatch)
    record = run_weather(config, tmp_path, Path("weather.toml"))
    assert len(fits) == record["models_fitted"] == 6
    assert len({id(p[0]) for p in pipelines}) == 6
    assert len({id(f[0]) for f in fits}) == 6
    assert all(np.isnan(x).any() for _, x, _ in fits)
    assert len(fits[0][2]) == len(fits[1][2]) == 72
    assert fits[0][2].max() == 10 and fits[-1][2].max() == 100
    assert record["control_models_refitted"] == 0
    assert record["test_metrics"] is None
    assert record["validation_rows"] == 144
    predictions = pd.concat(
        [
            pd.read_parquet(f)
            for f in sorted(
                (tmp_path / "artifacts/weather_ablation" / record["weather_ablation_id"]).glob(
                    "fold_*.parquet"
                )
            )
        ]
    )
    assert predictions.hour.max() < local_boundary(spec["study"]["sealed_test_start"])
    assert pooled_scores(predictions, list(record["pooled_metrics"])) == record["pooled_metrics"]
    assert (tmp_path / "artifacts/model.joblib").read_bytes() == b"preserve serving model"
    assert (tmp_path / "reports/latest_latency.json").read_text() == "preserve control report"


@pytest.mark.parametrize(
    "defect",
    ["snapshot_hash", "source", "last_control", "future_observation", "missing_weather_hour"],
)
def test_invalid_final_inputs_fail_before_first_fit(defect, weather_fixture, tmp_path, monkeypatch):
    config, spec, _ = weather_fixture
    fits, _ = recording_factory(monkeypatch)
    if defect == "source":
        (tmp_path / "src/nyc_mobility/features/weather_bundle.py").write_text("changed")
    elif defect == "last_control":
        path = tmp_path / "artifacts/latency/artificial-control/delay_0_fold_3.parquet"
        path.unlink()
    else:
        path = tmp_path / spec["weather"]["snapshots_file"]
        snapshots = pd.read_parquet(path)
        if defect == "missing_weather_hour":
            snapshots = snapshots.iloc[:-1]
        else:
            snapshots.loc[snapshots.index[-1], "observed_at"] = snapshots.hour.iloc[-1]
        snapshots.to_parquet(path, index=False)
        if defect != "snapshot_hash":
            spec["weather"]["snapshots_sha256"] = sha256(path)
            record_path = tmp_path / spec["weather"]["metrics_file"]
            record = json.loads(record_path.read_text())
            record["outputs_sha256"][spec["weather"]["snapshots_file"]] = sha256(path)
            write_json(record_path, record)
            spec["weather"]["metrics_sha256"] = sha256(record_path)
            write_protocol(tmp_path / "weather.toml", spec)
    with pytest.raises(ValueError):
        run_weather(config, tmp_path, Path("weather.toml"))
    assert fits == []


def test_fit_failure_stops_without_retry_or_success_report(weather_fixture, tmp_path, monkeypatch):
    config, _, _ = weather_fixture

    def fail(count):
        if count == 2:
            raise RuntimeError("synthetic fit failure")

    fits, _ = recording_factory(monkeypatch, fail)
    with pytest.raises(RuntimeError, match="synthetic fit failure"):
        run_weather(config, tmp_path, Path("weather.toml"))
    assert len(fits) == 2
    assert not (tmp_path / "reports/latest_weather_ablation.json").exists()
    assert len(list((tmp_path / "reports/weather_ablation").glob("*/failure.json"))) == 1


def test_midrun_source_mutation_prevents_success_publication(
    weather_fixture, tmp_path, monkeypatch
):
    config, _, _ = weather_fixture

    def mutate(count):
        if count == 1:
            with (tmp_path / "src/nyc_mobility/features/weather_bundle.py").open("a") as stream:
                stream.write("\n")

    recording_factory(monkeypatch, mutate)
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        run_weather(config, tmp_path, Path("weather.toml"))
    assert not (tmp_path / "reports/latest_weather_ablation.json").exists()


def test_append_preserves_order_and_rejects_missing_hour():
    hours = pd.date_range("2026-03-08T06:00Z", periods=3, freq="h")
    temporal = pd.DataFrame(
        {"zone_id": [3, 2, 2], "hour": hours[[2, 0, 2]], "demand": [4, 2, 1]}, index=[8, 4, 2]
    )
    bundle = pd.DataFrame(np.nan, index=range(3), columns=WEATHER_BUNDLE_FEATURES)
    bundle.insert(0, "hour", hours)
    combined = append_weather(temporal, bundle)
    pd.testing.assert_frame_equal(combined[list(temporal)], temporal)
    assert combined[WEATHER_BUNDLE_FEATURES].isna().all().all()
    with pytest.raises(ValueError):
        append_weather(temporal, bundle.iloc[:2])
