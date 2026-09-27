"""Small synthetic preflight verifies sealed targets and weather-independent row counts."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sklearn.ensemble import HistGradientBoostingRegressor

import nyc_mobility.data.weather_features as module
from nyc_mobility.evaluation.splits import expanding_folds, local_boundary
from nyc_mobility.features.weather import WEATHER_VALUES
from nyc_mobility.features.weather_bundle import WEATHER_BUNDLE_FEATURES, WEATHER_STATIONS


def fixture_files(
    root: Path, monkeypatch, *, source_policy="documented-sources-with-unverified-v1"
):
    start, stop = local_boundary("2026-04-20"), local_boundary("2026-05-01")
    targets = pd.date_range(start, stop, freq="h", inclusive="left")
    snapshots = pd.DataFrame(
        [
            {"hour": hour, "station_id": station, "delay_hours": delay}
            for delay in (3, 6)
            for station in WEATHER_STATIONS.values()
            for hour in targets
        ]
    )
    for column in ("observed_at", "assumed_available_at"):
        snapshots[column] = pd.Series(pd.NaT, index=snapshots.index, dtype="datetime64[ns, UTC]")
    snapshots["age_hours"] = np.nan
    for column in WEATHER_VALUES:
        snapshots[column] = np.nan
        snapshots[column + "_quality"] = "missing"
    snapshot_path = root / "artifacts/weather_policy/synthetic/snapshots.parquet"
    snapshot_path.parent.mkdir(parents=True)
    snapshots.to_parquet(snapshot_path, index=False)
    snapshot_hash = module.sha256(snapshot_path)
    record = {
        "weather_id": "synthetic",
        "policy": {"quality": source_policy, "max_age_hours": 12},
        "test_metrics": None,
        "models_fitted": 0,
        "outputs_sha256": {str(snapshot_path.relative_to(root)): snapshot_hash},
        "window_start_utc": start.isoformat(),
        "window_end_utc_exclusive": stop.isoformat(),
    }
    metrics_path = root / "reports/weather_policy/synthetic/metrics.json"
    metrics_path.parent.mkdir(parents=True)
    metrics_path.write_text(json.dumps(record))
    panel_path = root / "data/processed/hourly_demand.parquet"
    panel_path.parent.mkdir(parents=True)
    # A poisoned held-out label is valid Parquet but must never reach feature creation.
    pd.DataFrame(
        {
            "zone_id": 2,
            "hour": targets.append(pd.DatetimeIndex([stop])),
            "demand": [2.0] * len(targets) + [-999.0],
        }
    ).to_parquet(panel_path, index=False)
    lookup_path = root / "data/external/taxi_zone_lookup.csv"
    lookup_path.parent.mkdir(parents=True)
    lookup_path.write_text("synthetic lookup; mocked zone reader")
    (root / "uv.lock").write_text("synthetic lock")
    bundle_source = root / "src/nyc_mobility/features/weather_bundle.py"
    bundle_source.parent.mkdir(parents=True)
    bundle_source.write_text("# synthetic source provenance fixture\n")
    boundaries = ["2026-04-28", "2026-04-29", "2026-04-30", "2026-05-01"]
    folds = expanding_folds("2026-04-20", boundaries, "2026-05-01")
    control_path = root / "reports/latency/synthetic/metrics.json"
    control_path.parent.mkdir(parents=True)
    control_path.write_text("synthetic control; mocked loader")
    prediction_dir = root / "artifacts/latency/synthetic"
    prediction_dir.mkdir(parents=True)
    prediction_hashes = {}
    controls, details = {}, []
    for fold in folds:
        predictions = prediction_dir / f"delay_0_{fold.name}.parquet"
        predictions.write_bytes(b"synthetic predictions; mocked loader")
        prediction_hashes[fold.name] = module.sha256(predictions)
        controls[fold.name] = pd.DataFrame(
            {"hour": targets[(targets >= fold.validation_start) & (targets < fold.validation_end)]}
        )
        details.append(
            {"name": fold.name, "delay_hours": 0, "training_targets_sha256": "synthetic"}
        )
    spec = root / "weather_ablation.toml"
    spec.write_text(
        f'''[study]
train_start = "2026-04-20"
sealed_test_start = "2026-05-01"
weather_delays_hours = [3, 6]
fit_budget = 6
common_warmup_hours = 174
common_training_embargo_hours = 6
observation_delay_hours = 0
validation_boundaries = {json.dumps(boundaries)}
[weather]
features = {json.dumps(WEATHER_BUNDLE_FEATURES)}
bundle_source_sha256 = "{module.sha256(bundle_source)}"
weather_id = "synthetic"
metrics_file = "{metrics_path.relative_to(root)}"
metrics_sha256 = "{module.sha256(metrics_path)}"
snapshots_file = "{snapshot_path.relative_to(root)}"
snapshots_sha256 = "{snapshot_hash}"
lookup_sha256 = "{module.sha256(lookup_path)}"
[control]
latency_id = "synthetic"
data_sha256 = "{module.sha256(panel_path)}"
metrics_sha256 = "{module.sha256(control_path)}"
[control.prediction_sha256]
'''
        + "\n".join(f'{name} = "{digest}"' for name, digest in prediction_hashes.items())
    )
    monkeypatch.setattr(module, "load_zones", lambda path: pd.DataFrame({"zone_id": [2]}))
    monkeypatch.setattr(
        module, "load_control", lambda *args, **kwargs: ({"folds": details}, controls)
    )
    matched = []

    def match(features, fold, zones, study, saved, detail):
        assert features.hour.lt(stop).all() and features.demand.ge(0).all()
        assert zones == [2]
        train_start = start + pd.Timedelta(hours=174)
        train_end = fold.validation_start - pd.Timedelta(hours=6)
        train = features.loc[features.hour.between(train_start, train_end, inclusive="left")]
        valid = features.loc[
            features.hour.between(fold.validation_start, fold.validation_end, inclusive="left")
        ]
        assert len(valid) == len(saved) == 24
        matched.append((fold.name, len(train), len(valid)))
        return train, valid

    monkeypatch.setattr(module, "matched_fold", match)
    config = {"split": {"train_start": "2026-04-20", "test_start": "2026-05-01"}}
    return spec, config, snapshot_path, panel_path, matched


def forbidden(*args, **kwargs):
    raise AssertionError("Rejected preflight reached a target read or a model fit")


@pytest.mark.parametrize(
    "old, new, message",
    [
        ("fit_budget = 6", "fit_budget = 7", "bounded comparison contract"),
        ('"2026-04-30", "2026-05-01"', '"2026-04-30", "2026-05-02"', "held-out"),
    ],
)
def test_invalid_protocol_or_heldout_bounds_fail_before_data_io(
    tmp_path, monkeypatch, old, new, message
):
    spec, config, *_ = fixture_files(tmp_path, monkeypatch)
    spec.write_text(spec.read_text().replace(old, new))
    monkeypatch.setattr(module, "checked_hash", forbidden)
    monkeypatch.setattr(pd, "read_parquet", forbidden)
    with pytest.raises(ValueError, match=message):
        module.prepare_weather_features(config, tmp_path, spec)
    assert not (tmp_path / "reports/weather_features").exists()


def test_source_policy_is_checked_before_weather_or_target_read(tmp_path, monkeypatch):
    spec, config, *_ = fixture_files(tmp_path, monkeypatch, source_policy="source-223-good-only")
    monkeypatch.setattr(pd, "read_parquet", forbidden)
    with pytest.raises(ValueError, match="retrospective policy"):
        module.prepare_weather_features(config, tmp_path, spec)
    assert not (tmp_path / "reports/weather_features").exists()


def test_changed_weather_snapshot_hash_fails_before_read(tmp_path, monkeypatch):
    spec, config, snapshot_path, *_ = fixture_files(tmp_path, monkeypatch)
    snapshot_path.write_bytes(b"changed after protocol was pinned")
    monkeypatch.setattr(pd, "read_parquet", forbidden)
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        module.prepare_weather_features(config, tmp_path, spec)
    assert not (tmp_path / "reports/weather_features").exists()


def test_preparation_retains_every_target_with_missing_weather_and_performs_no_fit(
    tmp_path, monkeypatch
):
    spec, config, snapshot_path, panel_path, matched = fixture_files(tmp_path, monkeypatch)
    original_read = pd.read_parquet
    reads = []

    def safe_read(path, **kwargs):
        reads.append(path)
        if path == panel_path:
            assert kwargs["filters"] == [
                ("hour", ">=", local_boundary("2026-04-20")),
                ("hour", "<", local_boundary("2026-05-01")),
            ]
        else:
            assert path == snapshot_path
        return original_read(path, **kwargs)

    monkeypatch.setattr(pd, "read_parquet", safe_read)
    monkeypatch.setattr(HistGradientBoostingRegressor, "fit", forbidden)
    result = module.prepare_weather_features(config, tmp_path, spec)
    assert reads == [snapshot_path, panel_path]
    assert len(matched) == 3
    assert result["models_fitted"] == 0 and result["test_metrics"] is None
    assert result["serving_model_changed"] is False
    assert result["historical_weather_publication_verified"] is False
    assert result["validation_rows_per_candidate"] == 72
    output = tmp_path / "reports/weather_features" / result["preparation_id"]
    preflight = pd.read_csv(output / "control_preflight.csv")
    assert len(preflight) == 6 and preflight.validation_rows.eq(24).all()
    assert preflight.weather_filter_rows_removed.eq(0).all()
    for delay in (3, 6):
        artifact = (
            tmp_path
            / "artifacts/weather_features"
            / result["preparation_id"]
            / f"delay_{delay}.parquet"
        )
        bundle = original_read(artifact)
        assert len(bundle) == result["hours_per_bundle"] == 264
        assert bundle.hour.lt(local_boundary("2026-05-01")).all()
        assert bundle.weather_lga_temperature_c.isna().all()
        assert bundle.weather_lga_temperature_c_missing.eq(1).all()
