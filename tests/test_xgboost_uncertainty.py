"""Artificial errors check multiplicity and isolation, not model performance."""

import copy
import json
import tomllib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from nyc_mobility.data.download import sha256
from nyc_mobility.evaluation.xgboost_uncertainty import (
    CONTRASTS,
    family_comparisons,
    run_xgboost_uncertainty,
    validate_protocol,
)


def protocol():
    return tomllib.loads(Path("configs/xgboost_uncertainty.toml").read_text())


def test_family_intervals_use_two_contrasts_and_correct_percentiles():
    spec = protocol()
    names = ["hist_gradient_boosting", "xgboost_depth4", "xgboost_depth6"]
    draws = np.array([[10, 8, 12], [10, 9, 11], [10, 10, 10], [10, 11, 9], [10, 12, 8]])
    results = family_comparisons(draws, np.array([10, 10, 10]), names, spec)
    assert len(results) == 2
    for row in results:
        assert row["delta_mae"] == 0
        assert row["delta_mae_low"] == pytest.approx(-1.9)
        assert row["delta_mae_high"] == pytest.approx(1.9)
        assert row["delta_mae_family_low"] == pytest.approx(-1.95)
        assert row["delta_mae_family_high"] == pytest.approx(1.95)
        assert row["per_contrast_confidence_level"] == pytest.approx(0.975)
        assert row["relative_reduction_pct_low"] == pytest.approx(-19)
        assert row["relative_reduction_pct_high"] == pytest.approx(19)
        assert "relative_reduction_pct_family_low" not in row
    spec["contrasts"] = [spec["contrasts"][0]]
    with pytest.raises(ValueError, match="Family size"):
        family_comparisons(draws, np.array([10, 10, 10]), names, spec)


@pytest.mark.parametrize(
    "defect",
    [
        "winner_only",
        "duplicate",
        "extra",
        "size",
        "metric",
        "confidence",
        "duplicate_blocks",
        "float_block",
        "bool_block",
        "seed",
        "replicates",
    ],
)
def test_protocol_rejects_changed_family_or_invalid_resampling(defect):
    spec = protocol()
    if defect == "winner_only":
        spec["contrasts"].pop(0)
    elif defect == "duplicate":
        spec["contrasts"][0] = spec["contrasts"][1]
    elif defect == "extra":
        spec["contrasts"].append({"candidate": "xgboost_depth6", "reference": "previous_week_168h"})
    elif defect == "size":
        spec["study"]["family_size"] = 1
    elif defect == "metric":
        spec["study"]["family_metric"] = "relative_reduction_pct"
    elif defect == "confidence":
        spec["study"]["family_confidence_level"] = 1
    elif defect == "duplicate_blocks":
        spec["study"]["sensitivity_block_days"] = [7, 14]
    elif defect == "float_block":
        spec["study"]["primary_block_days"] = 7.5
    elif defect == "bool_block":
        spec["study"]["primary_block_days"] = True
    elif defect == "seed":
        spec["study"]["random_seed"] = -1
    else:
        spec["study"]["replicates"] = 1
    with pytest.raises(ValueError):
        validate_protocol(spec)


def setup_run(tmp_path):
    names = ["hist_gradient_boosting", "xgboost_depth4", "xgboost_depth6"]
    weights = [48, 46, 48]
    daily = pd.DataFrame(
        [
            {"fold": "march", "date_nyc": day, "model": name, "rows": count, "mae": mae}
            for name, losses in zip(names, [[2, 5, 7], [3, 6, 8], [1, 4, 6]], strict=True)
            for day, count, mae in zip(
                ["2026-03-07", "2026-03-08", "2026-03-09"], weights, losses, strict=True
            )
        ]
    )
    scores = {
        name: {"mae": float(np.average(part.mae, weights=part.rows))}
        for name, part in daily.groupby("model", sort=False)
    }
    record = {
        "xgboost_id": "artificial-only",
        "protocol": {"study": {"sealed_test_start": "2026-03-10"}},
        "test_metrics": None,
        "validation_rows": 142,
        "pooled_metrics": scores,
        "folds": [
            {
                "name": "march",
                "validation_start": "2026-03-07T05:00:00+00:00",
                "validation_end": "2026-03-10T04:00:00+00:00",
                "validation_rows": 142,
                "metrics": copy.deepcopy(scores),
            }
        ],
    }
    source = tmp_path / "reports/xgboost/artificial-only"
    source.mkdir(parents=True)
    (source / "metrics.json").write_text(json.dumps(record))
    daily.to_csv(source / "daily_mae.csv", index=False)
    spec = protocol()
    spec["study"].update(
        xgboost_id="artificial-only",
        primary_block_days=2,
        sensitivity_block_days=[1, 3],
        replicates=100,
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
    return path, source


def test_pipeline_reads_only_summaries_and_preserves_prior_reports(tmp_path, monkeypatch):
    import joblib
    from sklearn.ensemble import HistGradientBoostingRegressor
    from xgboost import XGBRegressor

    path, source = setup_run(tmp_path)
    sentinels = [
        "artifacts/model.joblib",
        "data/processed/hourly_demand.parquet",
        "reports/latest_uncertainty.json",
        "reports/latest_xgboost.json",
        "reports/latest_latency.json",
        "reports/latest_experiment.json",
    ]
    for name in sentinels:
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"preserve")

    def forbidden(*args, **kwargs):
        raise AssertionError("Summary analysis must not load Parquet/models or fit")

    monkeypatch.setattr(pd, "read_parquet", forbidden)
    monkeypatch.setattr(joblib, "load", forbidden)
    monkeypatch.setattr(HistGradientBoostingRegressor, "fit", forbidden)
    monkeypatch.setattr(XGBRegressor, "fit", forbidden)
    before = {p: sha256(p) for p in source.iterdir()}
    result = run_xgboost_uncertainty({"split": {"test_start": "2026-03-10"}}, tmp_path, path)
    assert result["validation_rows"] == 142 and result["validation_days"] == 3
    assert len(result["comparisons"]) == 6
    assert result["models_refitted"] == 0 and result["test_metrics"] is None
    assert {p: sha256(p) for p in source.iterdir()} == before
    assert all((tmp_path / p).read_bytes() == b"preserve" for p in sentinels)
    saved = tmp_path / "reports/latest_xgboost_uncertainty.json"
    assert json.loads(saved.read_text())["comparisons"] == result["comparisons"]
    for row in result["comparisons"]:
        expected = 1 if row["candidate"] == "xgboost_depth4" else -1
        assert row["delta_mae_family_low"] == pytest.approx(expected)
        assert row["delta_mae_family_high"] == pytest.approx(expected)
    artifact = tmp_path / "artifacts/xgboost_uncertainty" / result["uncertainty_id"] / "draws.npz"
    with np.load(artifact, allow_pickle=False) as draws:
        assert draws["block_2_mae"].shape == (100, 3)
        np.testing.assert_allclose(draws["block_2_mae"][:, 1] - draws["block_2_mae"][:, 0], 1)


@pytest.mark.parametrize("defect", ["hash", "identifier", "missing_day", "held_out", "long_block"])
def test_bad_inputs_abort_before_resampling(tmp_path, monkeypatch, defect):
    import nyc_mobility.evaluation.xgboost_uncertainty as module

    path, source = setup_run(tmp_path)
    if defect in ["hash", "missing_day"]:
        p = source / "daily_mae.csv"
        old_hash = sha256(p)
        pd.read_csv(p).iloc[1:].to_csv(p, index=False)
        if defect == "missing_day":
            path.write_text(path.read_text().replace(old_hash, sha256(p)))
    elif defect in ["identifier", "held_out"]:
        p = source / "metrics.json"
        old_hash = sha256(p)
        record = json.loads(p.read_text())
        if defect == "identifier":
            record["xgboost_id"] = "wrong"
        else:
            record["folds"][0]["validation_end"] = "2026-03-11T04:00:00+00:00"
        p.write_text(json.dumps(record))
        path.write_text(path.read_text().replace(old_hash, sha256(p)))
    else:
        path.write_text(
            path.read_text().replace("primary_block_days = 2", "primary_block_days = 4")
        )

    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid input reached sampling")

    monkeypatch.setattr(module, "bootstrap_mae", forbidden)
    with pytest.raises(ValueError):
        run_xgboost_uncertainty({"split": {"test_start": "2026-03-10"}}, tmp_path, path)
    assert not (tmp_path / "reports/xgboost_uncertainty").exists()


def test_protocol_mutation_during_sampling_prevents_publication(tmp_path, monkeypatch):
    import nyc_mobility.evaluation.xgboost_uncertainty as module

    path, _ = setup_run(tmp_path)
    original = module.bootstrap_mae

    def mutate(*args, **kwargs):
        path.write_text(path.read_text() + "\n")
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "bootstrap_mae", mutate)
    with pytest.raises(ValueError, match="changed during"):
        run_xgboost_uncertainty({"split": {"test_start": "2026-03-10"}}, tmp_path, path)
    assert not (tmp_path / "reports/xgboost_uncertainty").exists()
