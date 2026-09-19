"""Artificial errors test resampling behavior; none are published performance results."""

import copy
import json

import numpy as np
import pandas as pd
import pytest

from nyc_mobility.data.download import sha256
from nyc_mobility.evaluation.uncertainty import (
    bootstrap_mae,
    circular_indices,
    compare_draws,
    run_uncertainty,
    validate_daily_errors,
)


def fixture_errors():
    weights = np.array([48, 46, 48])  # Two zones: March 8 has 23 hours.
    daily = pd.DataFrame(
        [
            {"fold": "march", "date_nyc": day, "model": model, "rows": rows, "mae": value}
            for model, values in [("reference", [2, 5, 7]), ("candidate", [1, 3, 4])]
            for day, rows, value in zip(
                ["2026-03-07", "2026-03-08", "2026-03-09"], weights, values, strict=True
            )
        ]
    )
    scores = {
        model: {"mae": float(np.average(part.mae, weights=part.rows))}
        for model, part in daily.groupby("model", sort=False)
    }
    backtest = {
        "backtest_id": "unit-test-only",
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
    return daily, backtest


def test_daily_alignment_reconciles_dst_and_ignores_input_order():
    daily, record = fixture_errors()
    names, folds = validate_daily_errors(daily.sample(frac=1, random_state=1), record, "2026-03-10")
    assert names == ["reference", "candidate"]
    weights, losses = folds[0]
    np.testing.assert_array_equal(weights, [48, 46, 48])
    np.testing.assert_array_equal(losses, [[2, 1], [5, 3], [7, 4]])
    assert np.average(losses[:, 0], weights=weights) != losses[:, 0].mean()


@pytest.mark.parametrize(
    "defect",
    [
        "missing",
        "duplicate",
        "extra_test_day",
        "dst_count",
        "nan",
        "negative",
        "fold_mae",
        "pooled_mae",
        "test_boundary",
        "test_scored",
        "missing_model",
        "fractional_count",
    ],
)
def test_invalid_daily_inputs_fail_before_sampling(defect):
    daily, record = fixture_errors()
    if defect == "missing":
        daily = daily.drop(index=0)
    elif defect == "duplicate":
        daily = pd.concat([daily, daily.iloc[[0]]])
    elif defect == "extra_test_day":
        daily.loc[0, "date_nyc"] = "2026-03-10"
    elif defect == "dst_count":
        daily.loc[daily.date_nyc == "2026-03-08", "rows"] = 48
    elif defect == "nan":
        daily.loc[0, "mae"] = np.nan
    elif defect == "negative":
        daily.loc[0, "mae"] = -1
    elif defect == "fold_mae":
        record["folds"][0]["metrics"]["candidate"]["mae"] += 0.1
    elif defect == "pooled_mae":
        record["pooled_metrics"]["candidate"]["mae"] += 0.1
    elif defect == "test_boundary":
        record["folds"][0]["validation_end"] = "2026-03-11T04:00:00+00:00"
    elif defect == "test_scored":
        record["test_metrics"] = {"mae": 1}
    elif defect == "missing_model":
        daily = daily.loc[daily.model != "candidate"]
    else:
        daily["rows"] = daily.rows.astype(float)
        daily.loc[0, "rows"] = 47.5
    with pytest.raises(ValueError):
        validate_daily_errors(daily, record, "2026-03-10")


def test_circular_blocks_wrap_then_trim_without_reordering_days():
    class FixedStarts:
        def integers(self, high, size):
            assert high == 5 and size == (2, 2)
            return np.array([[4, 1], [3, 0]])

    indices = circular_indices(5, 3, 2, FixedStarts())
    np.testing.assert_array_equal(indices, [[4, 0, 1, 1, 2], [3, 4, 0, 0, 1]])


@pytest.mark.parametrize("block", [0, -1, 4, 1.5, True])
def test_invalid_block_lengths_fail(block):
    with pytest.raises(ValueError):
        circular_indices(3, block, 10, np.random.default_rng(42))


def test_resamples_pair_models_weight_counts_and_keep_fold_strata(monkeypatch):
    import nyc_mobility.evaluation.uncertainty as module

    calls = []

    def fixed_indices(days, block, replicates, rng):
        calls.append(days)
        return np.array([[0, 0, 1]]) if days == 3 else np.array([[1, 1]])

    monkeypatch.setattr(module, "circular_indices", fixed_indices)
    folds = [
        (np.array([48, 46, 48]), np.array([[1, 3], [4, 6], [9, 11]])),
        (np.array([48, 48]), np.array([[10, 12], [20, 22]])),
    ]
    draws = bootstrap_mae(folds, 1, 1, 42)
    expected = (48 * 1 * 2 + 46 * 4 + 48 * 20 * 2) / (48 * 2 + 46 + 48 * 2)
    np.testing.assert_allclose(draws, [[expected, expected + 2]])
    assert calls == [3, 2]


def test_seeded_draws_and_constant_paired_difference():
    folds = [(np.array([48, 46, 48]), np.array([[1, 3], [4, 6], [9, 11]]))]
    draws = bootstrap_mae(folds, 2, 100, 42)
    np.testing.assert_array_equal(draws, bootstrap_mae(folds, 2, 100, 42))
    np.testing.assert_allclose(draws[:, 1] - draws[:, 0], 2)
    assert not np.array_equal(draws, bootstrap_mae(folds, 2, 100, 43))
    protocol = {
        "study": {"confidence_level": 0.95},
        "contrasts": [{"candidate": "c", "reference": "r"}],
    }
    result = compare_draws(draws, np.array([4, 6]), ["r", "c"], protocol)[0]
    assert result["delta_mae"] == 2
    assert result["delta_mae_low"] == pytest.approx(2)
    assert result["delta_mae_high"] == pytest.approx(2)
    assert result["relative_reduction_pct"] == -50
    with pytest.raises(ValueError, match="zero-MAE"):
        compare_draws(np.zeros((10, 2)), np.zeros(2), ["r", "c"], protocol)


def test_percentile_intervals_use_linear_quantiles_and_correct_direction():
    protocol = {
        "study": {"confidence_level": 0.5},
        "contrasts": [{"candidate": "c", "reference": "r"}],
    }
    result = compare_draws(
        np.array([[2, 0], [2, 2], [2, 4], [2, 6]]), np.array([2, 3]), ["r", "c"], protocol
    )[0]
    assert result["delta_mae_low"] == -0.5
    assert result["delta_mae_high"] == 2.5
    assert result["relative_reduction_pct_low"] == -125
    assert result["relative_reduction_pct_high"] == 25


def test_full_fold_blocks_preserve_point_mae_even_with_unequal_day_weights():
    daily, record = fixture_errors()
    names, folds = validate_daily_errors(daily, record, "2026-03-10")
    draws = bootstrap_mae(folds, 3, 50, 42)
    point = [record["pooled_metrics"][name]["mae"] for name in names]
    np.testing.assert_allclose(draws, np.tile(point, (50, 1)))


def setup_run(tmp_path):
    daily, record = fixture_errors()
    source = tmp_path / "reports/backtests/unit-test-only"
    source.mkdir(parents=True)
    (source / "metrics.json").write_text(json.dumps(record))
    daily.to_csv(source / "daily_mae.csv", index=False)
    protocol = tmp_path / "uncertainty.toml"
    protocol.write_text(f'''[study]
id = "unit-test-only"
backtest_id = "unit-test-only"
backtest_metrics_sha256 = "{sha256(source / "metrics.json")}"
daily_mae_sha256 = "{sha256(source / "daily_mae.csv")}"
method = "fold-stratified-circular-day-blocks"
primary_block_days = 2
sensitivity_block_days = [1, 3]
replicates = 100
confidence_level = 0.95
random_seed = 42
[[contrasts]]
candidate = "candidate"
reference = "reference"
''')
    (tmp_path / "uv.lock").write_text("test-only lock")
    return protocol, source


def test_uncertainty_stage_reuses_summaries_and_preserves_existing_artifacts(tmp_path, monkeypatch):
    protocol, source = setup_run(tmp_path)
    sentinels = [
        "artifacts/model.joblib",
        "data/processed/hourly_demand.parquet",
        "reports/latest_backtest.json",
        "reports/latest_experiment.json",
    ]
    for name in sentinels:
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"must not read or change")

    def forbidden(*args, **kwargs):
        raise AssertionError("Uncertainty must not read target Parquet files")

    monkeypatch.setattr(pd, "read_parquet", forbidden)
    before = {p: sha256(p) for p in source.iterdir()}
    result = run_uncertainty({"split": {"test_start": "2026-03-10"}}, tmp_path, protocol)
    assert result["validation_days"] == 3 and result["validation_rows"] == 142
    assert len(result["comparisons"]) == 3
    assert result["models_refitted"] == 0 and result["test_metrics"] is None
    assert {p: sha256(p) for p in source.iterdir()} == before
    assert all((tmp_path / p).read_bytes() == b"must not read or change" for p in sentinels)
    output = tmp_path / "reports/uncertainty" / result["uncertainty_id"]
    assert json.loads((output / "metrics.json").read_text())["comparisons"] == result["comparisons"]
    artifact = tmp_path / "artifacts/uncertainty" / result["uncertainty_id"] / "draws.npz"
    with np.load(artifact, allow_pickle=False) as draws:
        assert draws["block_2_mae"].shape == (100, 2)


def test_changed_input_hash_aborts_without_writing_results(tmp_path):
    protocol, source = setup_run(tmp_path)
    with (source / "daily_mae.csv").open("a") as stream:
        stream.write("\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        run_uncertainty({"split": {"test_start": "2026-03-10"}}, tmp_path, protocol)
    assert not (tmp_path / "reports/uncertainty").exists()
