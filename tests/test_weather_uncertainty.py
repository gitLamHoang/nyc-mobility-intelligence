"""Artificial daily errors test isolation, pairing and the frozen weather protocol."""

import copy
import json
import shutil
import tomllib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from nyc_mobility.data.download import sha256
from nyc_mobility.evaluation.weather_uncertainty import (
    BOUNDARIES,
    CONTRASTS,
    MODELS,
    family_comparisons,
    run_weather_uncertainty,
    validate_protocol,
)


def protocol():
    return tomllib.loads(Path("configs/weather_uncertainty.toml").read_text())


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("id", "changed"),
        ("method", "independent-days"),
        ("primary_weather_delay_hours", 6),
        ("primary_block_days", 14),
        ("primary_block_days", 7.0),
        ("sensitivity_block_days", [True, 14]),
        ("sensitivity_block_days", [14, 1]),
        ("replicates", 9999),
        ("random_seed", 0),
        ("confidence_level", 0.9),
        ("family_confidence_level", 0.9),
        ("family_size", 3),
        ("family_size", True),
        ("family_metric", "relative_reduction_pct"),
        ("family_method", "none"),
        ("weather_ablation_id", "../escape"),
        ("daily_mae_sha256", "invalid"),
        ("metrics_sha256", "invalid"),
        ("new_setting", 1),
    ],
)
def test_protocol_rejects_changed_settings(key, value):
    spec = protocol()
    spec["study"][key] = value
    with pytest.raises(ValueError):
        validate_protocol(spec)


@pytest.mark.parametrize("defect", ["missing", "duplicate", "extra", "reordered"])
def test_protocol_rejects_changed_family(defect):
    spec = protocol()
    if defect == "missing":
        spec["contrasts"].pop()
    elif defect == "duplicate":
        spec["contrasts"][0] = spec["contrasts"][1]
    elif defect == "extra":
        spec["contrasts"].append({"candidate": "weather_3h", "reference": "weather_6h"})
    else:
        spec["contrasts"].reverse()
    with pytest.raises(ValueError, match="exactly the two"):
        validate_protocol(spec)


def test_two_contrast_family_percentiles_leave_relative_intervals_marginal():
    names = ["hist_gradient_boosting", "weather_3h", "weather_6h"]
    draws = np.array([[10, 8, 12], [10, 9, 11], [10, 10, 10], [10, 11, 9], [10, 12, 8]])
    rows = family_comparisons(draws, np.array([10, 10, 10]), names, protocol())
    assert len(rows) == 2
    for row in rows:
        candidate = names.index(row["candidate"])
        delta = draws[:, candidate] - draws[:, 0]
        relative = 100 * (1 - draws[:, candidate] / draws[:, 0])
        assert row["delta_mae_family_low"] == pytest.approx(np.quantile(delta, 0.0125))
        assert row["delta_mae_family_high"] == pytest.approx(np.quantile(delta, 0.9875))
        assert row["per_contrast_confidence_level"] == pytest.approx(0.975)
        assert row["relative_reduction_pct_low"] == pytest.approx(np.quantile(relative, 0.025))
        assert row["relative_reduction_pct_high"] == pytest.approx(np.quantile(relative, 0.975))
        assert "relative_reduction_pct_family_low" not in row


@pytest.fixture
def setup_run(tmp_path):
    names = sorted(MODELS)
    daily_rows, folds = [], []
    for number, (start, end) in enumerate(zip(BOUNDARIES[:-1], BOUNDARIES[1:], strict=True), 1):
        boundaries = pd.date_range(start, end, freq="D", tz="America/New_York")
        fold_rows = []
        for day, (left, right) in enumerate(zip(boundaries[:-1], boundaries[1:], strict=True)):
            count = int((right - left).total_seconds() / 3600) * 262
            for index, name in enumerate(names):
                offset = {"hist_gradient_boosting": 0, "weather_3h": 1, "weather_6h": -1}.get(
                    name, index + 2
                )
                mae = 3 + day % 5 + number + offset
                fold_rows.append(
                    {
                        "fold": f"fold_{number}",
                        "date_nyc": str(left.date()),
                        "model": name,
                        "rows": count,
                        "mae": mae,
                        "absolute_error_sum": count * mae,
                    }
                )
        frame = pd.DataFrame(fold_rows)
        scores = {
            name: {"mae": float(np.average(part.mae, weights=part.rows))}
            for name, part in frame.groupby("model", sort=False)
        }
        folds.append(
            {
                "name": f"fold_{number}",
                "validation_start": boundaries[0].isoformat(),
                "validation_end": boundaries[-1].isoformat(),
                "validation_rows": int(frame.loc[frame.model == names[0], "rows"].sum()),
                "metrics": scores,
            }
        )
        daily_rows.extend(fold_rows)
    daily = pd.DataFrame(daily_rows)
    scores = {
        name: {"mae": float(np.average(part.mae, weights=part.rows))}
        for name, part in daily.groupby("model", sort=False)
    }
    record = {
        "weather_ablation_id": "artificial-only",
        "protocol": {
            "study": {
                "validation_boundaries": BOUNDARIES,
                "sealed_test_start": "2026-05-01",
                "primary_weather_delay_hours": 3,
                "weather_delays_hours": [3, 6],
            }
        },
        "status": "completed",
        "models_fitted": 6,
        "fits_attempted": 6,
        "control_models_refitted": 0,
        "serving_model_changed": False,
        "historical_weather_publication_verified": False,
        "test_metrics": None,
        "validation_rows": 559370,
        "pooled_metrics": scores,
        "folds": folds,
    }
    source = tmp_path / "reports/weather_ablation/artificial-only"
    source.mkdir(parents=True)
    (source / "metrics.json").write_text(json.dumps(record))
    daily.to_csv(source / "daily_mae.csv", index=False)
    spec = protocol()
    spec["study"].update(
        weather_ablation_id="artificial-only",
        metrics_sha256=sha256(source / "metrics.json"),
        daily_mae_sha256=sha256(source / "daily_mae.csv"),
    )
    path = tmp_path / "protocol.toml"
    text = "[study]\n" + "\n".join(
        f"{key} = {json.dumps(value)}" for key, value in spec["study"].items()
    )
    for pair in CONTRASTS:
        text += "\n[[contrasts]]\n" + "\n".join(f'{k} = "{v}"' for k, v in pair.items())
    path.write_text(text)
    (tmp_path / "uv.lock").write_text("artificial-lock")
    (tmp_path / "docs").mkdir()
    shutil.copy("docs/WEATHER_UNCERTAINTY_PROTOCOL.md", tmp_path / "docs")
    (tmp_path / "src").mkdir()
    (tmp_path / "src/example.py").write_text("# artificial source")
    return path, source


def run(tmp_path, path):
    return run_weather_uncertainty({"split": {"test_start": "2026-05-01"}}, tmp_path, path)


def test_reads_only_summaries_pairs_all_models_and_reproduces(tmp_path, monkeypatch, setup_run):
    import joblib
    from sklearn.ensemble import HistGradientBoostingRegressor
    from xgboost import XGBRegressor

    path, source = setup_run
    sentinels = [
        "artifacts/model.joblib",
        "data/processed/hourly_demand.parquet",
        "reports/latest_weather_ablation.json",
        "reports/latest_weather.json",
        "reports/latest_weather_policy.json",
        "reports/latest_experiment.json",
        "web/public/data/demo.json",
    ]
    for name in sentinels:
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"preserve")

    def forbidden(*args, **kwargs):
        raise AssertionError("Summary analysis must not read targets/models or fit")

    monkeypatch.setattr(pd, "read_parquet", forbidden)
    monkeypatch.setattr(joblib, "load", forbidden)
    monkeypatch.setattr(HistGradientBoostingRegressor, "fit", forbidden)
    monkeypatch.setattr(XGBRegressor, "fit", forbidden)
    before = {p: sha256(p) for p in source.iterdir()}
    result = run(tmp_path, path)
    repeated = run(tmp_path, path)
    assert result["comparisons"] == repeated["comparisons"]
    assert result["uncertainty_id"] != repeated["uncertainty_id"]
    assert result["validation_rows"] == 559370 and result["validation_days"] == 89
    assert result["models_refitted"] == 0 and result["target_tables_read"] == 0
    assert result["test_metrics"] is None and result["serving_model_changed"] is False
    assert {p: sha256(p) for p in source.iterdir()} == before
    assert all((tmp_path / p).read_bytes() == b"preserve" for p in sentinels)
    assert len(result["comparisons"]) == 6
    for row in result["comparisons"]:
        expected = 1 if row["candidate"] == "weather_3h" else -1
        assert row["delta_mae_family_low"] == pytest.approx(expected)
        assert row["delta_mae_family_high"] == pytest.approx(expected)
        assert row["weather_role"] == ("primary" if expected == 1 else "sensitivity")
    artifact = tmp_path / "artifacts/weather_uncertainty" / result["uncertainty_id"] / "draws.npz"
    other = tmp_path / "artifacts/weather_uncertainty" / repeated["uncertainty_id"] / "draws.npz"
    with (
        np.load(artifact, allow_pickle=False) as first,
        np.load(other, allow_pickle=False) as second,
    ):
        for key in first.files:
            np.testing.assert_array_equal(first[key], second[key])
        names = first["model_names"].tolist()
        for block in [7, 1, 14]:
            assert first[f"block_{block}_mae"].shape == (10000, 8)
            np.testing.assert_allclose(
                first[f"block_{block}_mae"][:, names.index("weather_3h")]
                - first[f"block_{block}_mae"][:, names.index("hist_gradient_boosting")],
                1,
            )
    latest = json.loads((tmp_path / "reports/latest_weather_uncertainty.json").read_text())
    assert latest["comparisons"] == result["comparisons"]


@pytest.mark.parametrize(
    "defect",
    [
        "hash",
        "total",
        "nan_total",
        "negative_total",
        "missing_day",
        "duplicate_day",
        "wrong_dst",
        "missing_model",
        "fold_count",
        "boundary",
        "identifier",
        "point",
        "test_metrics",
        "fold_order",
        "promoted",
    ],
)
def test_bad_inputs_abort_before_sampling(tmp_path, monkeypatch, setup_run, defect):
    import nyc_mobility.evaluation.weather_uncertainty as module

    path, source = setup_run
    p = source / "daily_mae.csv"
    old_hash = sha256(p)
    daily = pd.read_csv(p)
    if defect in {"hash", "missing_day"}:
        daily = daily.iloc[1:]
    elif defect == "total":
        daily.loc[0, "absolute_error_sum"] += 1
    elif defect == "nan_total":
        daily.loc[0, "absolute_error_sum"] = np.nan
    elif defect == "negative_total":
        daily.loc[0, "absolute_error_sum"] = -1
    elif defect == "duplicate_day":
        daily = pd.concat([daily, daily.iloc[[0]]])
    elif defect == "wrong_dst":
        daily.loc[daily.date_nyc == "2026-03-08", "rows"] = 24 * 262
        daily["absolute_error_sum"] = daily.rows * daily.mae
    elif defect == "missing_model":
        daily = daily.loc[daily.model != "rolling_mean_24h"]
    else:
        p = source / "metrics.json"
        old_hash = sha256(p)
        record = json.loads(p.read_text())
        if defect == "fold_count":
            record["folds"].pop()
        elif defect == "boundary":
            record["folds"][0]["validation_start"] = "2026-02-02T05:00:00+00:00"
        elif defect == "identifier":
            record["weather_ablation_id"] = "wrong"
        elif defect == "point":
            record["pooled_metrics"]["weather_3h"]["mae"] += 1
        elif defect == "test_metrics":
            record["test_metrics"] = {}
        elif defect == "fold_order":
            record["folds"].reverse()
        else:
            record["serving_model_changed"] = True
        p.write_text(json.dumps(record))
    if p.suffix == ".csv":
        daily.to_csv(p, index=False)
    if defect != "hash":
        path.write_text(path.read_text().replace(old_hash, sha256(p)))

    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid input reached resampling")

    monkeypatch.setattr(module, "bootstrap_mae", forbidden)
    with pytest.raises(ValueError):
        run(tmp_path, path)
    assert not (tmp_path / "reports/weather_uncertainty").exists()


@pytest.mark.parametrize("target", ["protocol", "document", "source", "lock", "input"])
def test_midrun_mutation_prevents_publication(tmp_path, monkeypatch, setup_run, target):
    import nyc_mobility.evaluation.weather_uncertainty as module

    path, source = setup_run
    selected = {
        "protocol": path,
        "document": tmp_path / "docs/WEATHER_UNCERTAINTY_PROTOCOL.md",
        "source": tmp_path / "src/example.py",
        "lock": tmp_path / "uv.lock",
        "input": source / "daily_mae.csv",
    }[target]

    def mutate(folds, block, replicates, seed):
        selected.write_text(selected.read_text() + "\n")
        # Mutation behavior does not need real bootstrap work.
        return np.tile(folds[0][1][0], (replicates, 1))

    monkeypatch.setattr(module, "bootstrap_mae", mutate)
    with pytest.raises(ValueError, match="changed during"):
        run(tmp_path, path)
    assert not (tmp_path / "reports/weather_uncertainty").exists()
    assert not (tmp_path / "reports/latest_weather_uncertainty.json").exists()


def test_protocol_is_not_mutated_by_validation():
    spec = protocol()
    before = copy.deepcopy(spec)
    assert validate_protocol(spec) == [7, 1, 14]
    assert spec == before
