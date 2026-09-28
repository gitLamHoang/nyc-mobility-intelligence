"""Synthetic metadata catches fit-budget and evidence-manifest certification failures."""

import importlib.util
from pathlib import Path

import pytest

from nyc_mobility.data.download import sha256

spec = importlib.util.spec_from_file_location(
    "weather_verifier", Path(__file__).parents[1] / "scripts/verify_weather_ablation.py"
)
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)

FOLDS = {"fold_1", "fold_2", "fold_3"}


@pytest.fixture
def ledger():
    return {
        "status": "completed",
        "fits_attempted": 6,
        "models_fitted": 6,
        "fit_attempts": [
            {
                "fold": fold,
                "model": model,
                "status": "completed",
                "fit_completed": True,
                "fit_and_predict_seconds": 1.25,
            }
            for fold in sorted(FOLDS)
            for model in verifier.CANDIDATES
        ],
    }


def test_exact_six_completed_fit_pairs_are_verified(ledger):
    durations = verifier.verify_fit_ledger(ledger, FOLDS)
    assert set(durations) == {(fold, model) for fold in FOLDS for model in verifier.CANDIDATES}
    assert set(durations.values()) == {1.25}


@pytest.mark.parametrize(
    "defect",
    [
        "replacement",
        "duplicate",
        "missing",
        "unknown_fold",
        "unknown_model",
        "failed",
        "started",
        "not_fitted",
        "failed_study",
        "wrong_count",
        "noninteger_count",
    ],
)
def test_incomplete_or_expanded_fit_ledger_cannot_be_certified(ledger, defect):
    attempt = ledger["fit_attempts"][0]
    if defect == "replacement":
        # A superficially valid models_fitted=6 must not conceal a seventh attempt.
        ledger["fit_attempts"].append({**attempt, "status": "failed"})
        ledger["fits_attempted"] = 7
    elif defect == "duplicate":
        ledger["fit_attempts"][-1] = attempt.copy()
    elif defect == "missing":
        ledger["fit_attempts"].pop()
    elif defect in {"unknown_fold", "unknown_model"}:
        attempt[defect.removeprefix("unknown_")] = "unexpected"
    elif defect in {"failed", "started"}:
        attempt["status"] = defect
    elif defect == "not_fitted":
        attempt["fit_completed"] = False
    elif defect == "failed_study":
        ledger["status"] = "failed"
    elif defect == "wrong_count":
        ledger["models_fitted"] = 5
    else:
        ledger["fits_attempted"] = 6.0
    with pytest.raises(ValueError, match="[Ff]it ledger"):
        verifier.verify_fit_ledger(ledger, FOLDS)


@pytest.mark.parametrize("duration", [-1, float("nan"), float("inf"), None, "1.25", True])
def test_invalid_fit_duration_cannot_be_certified(ledger, duration):
    ledger["fit_attempts"][0]["fit_and_predict_seconds"] = duration
    with pytest.raises(ValueError, match="Fit ledger"):
        verifier.verify_fit_ledger(ledger, FOLDS)


@pytest.fixture
def report_manifest(tmp_path):
    manifest = {}
    for name in [
        "pooled_metrics",
        "fold_metrics",
        "slice_metrics",
        "daily_mae",
        "comparison",
        "preflight",
    ]:
        path = tmp_path / f"{name}.csv"
        path.write_text("synthetic,fixture\n1,2\n")
        manifest[str(path)] = sha256(path)
    return tmp_path, manifest


def test_all_six_report_output_hashes_are_verified(report_manifest):
    directory, manifest = report_manifest
    verifier.verify_output_hashes(directory, manifest)


@pytest.mark.parametrize("defect", ["changed", "missing", "extra", "wrong_directory"])
def test_report_manifest_defects_cannot_be_certified(report_manifest, defect):
    directory, manifest = report_manifest
    preflight = directory / "preflight.csv"
    if defect == "changed":
        preflight.write_text("changed after reporting\n")
    elif defect == "missing":
        del manifest[str(preflight)]
    elif defect == "extra":
        path = directory / "extra.csv"
        path.write_text("extra\n")
        manifest[str(path)] = sha256(path)
    else:
        directory = directory / "unrelated"
    with pytest.raises(ValueError):
        verifier.verify_output_hashes(directory, manifest)
