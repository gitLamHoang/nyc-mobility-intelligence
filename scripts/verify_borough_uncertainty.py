"""Verify saved borough intervals and reproduce from published summaries in isolation."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from nyc_mobility.config import write_json
from nyc_mobility.data.download import sha256


def verify(directory: Path, preservation_record: Path | None = None) -> dict:
    root = Path.cwd()
    record = json.loads((directory / "metrics.json").read_text())
    protocol = record["protocol"]
    assert sha256(root / "configs/borough_uncertainty.toml") == record["protocol_sha256"]
    assert sha256(root / "uv.lock") == record["lockfile_sha256"]
    for name, digest in {**record["input_sha256"], **record["source_hashes"]}.items():
        assert sha256(root / name) == digest, f"Changed evidence/source: {name}"
    source = root / "reports/borough" / protocol["study"]["borough_id"]
    study = json.loads((source / "metrics.json").read_text())
    artifact = root / "artifacts/borough_uncertainty" / record["uncertainty_id"] / "draws.npz"
    assert sha256(artifact) == record["draws_sha256"]
    contrasts = [(c["candidate"], c["reference"]) for c in protocol["contrasts"]]
    assert len(contrasts) == len(set(contrasts)) == 3
    comparisons = record["comparisons"]
    expected_keys = {(c, r, block) for c, r in contrasts for block in [7, 1, 14]}
    assert len(comparisons) == 9
    assert {(r["candidate"], r["reference"], r["block_days"]) for r in comparisons} == expected_keys
    assert record["models_refitted"] == record["target_tables_read"] == 0
    assert record["test_metrics"] is None and not record["serving_model_changed"]
    saved_csv = pd.read_csv(directory / "comparison.csv")
    pd.testing.assert_frame_equal(saved_csv, pd.DataFrame(comparisons), rtol=1e-12, atol=1e-15)
    largest_discrepancy = 0.0
    with np.load(artifact, allow_pickle=False) as draws:
        names = draws["model_names"].tolist()
        assert names == record["model_names"]
        assert set(draws.files) == {"model_names", "block_7_mae", "block_1_mae", "block_14_mae"}
        for row in comparisons:
            block = row["block_days"]
            values = draws[f"block_{block}_mae"]
            assert values.shape == (10000, len(names))
            assert np.isfinite(values).all() and (values >= 0).all()
            c, r = (names.index(row[k]) for k in ["candidate", "reference"])
            assert (values[:, r] > 0).all()
            delta = values[:, c] - values[:, r]
            relative = 100 * (1 - values[:, c] / values[:, r])
            marginal = np.quantile(delta, [0.025, 0.975], method="linear")
            adjusted = np.quantile(delta, [0.05 / 6, 1 - 0.05 / 6], method="linear")
            relative_ci = np.quantile(relative, [0.025, 0.975], method="linear")
            candidate = study["pooled_metrics"][row["candidate"]]["mae"]
            reference = study["pooled_metrics"][row["reference"]]["mae"]
            expected = {
                "delta_mae": candidate - reference,
                "delta_mae_low": marginal[0],
                "delta_mae_high": marginal[1],
                "delta_mae_family_low": adjusted[0],
                "delta_mae_family_high": adjusted[1],
                "relative_reduction_pct": 100 * (1 - candidate / reference),
                "relative_reduction_pct_low": relative_ci[0],
                "relative_reduction_pct_high": relative_ci[1],
            }
            assert row["role"] == ("primary" if block == 7 else "sensitivity")
            assert row["family_size"] == 3 and row["family_metric"] == "delta_mae"
            assert row["family_method"] == "bonferroni"
            assert row["confidence_level"] == row["family_confidence_level"] == 0.95
            assert np.isclose(row["per_contrast_confidence_level"], 1 - 0.05 / 3)
            for key, value in expected.items():
                discrepancy = abs(value - row[key])
                largest_discrepancy = max(largest_discrepancy, float(discrepancy))
                assert np.isclose(value, row[key], rtol=1e-12, atol=1e-14), key
        with tempfile.TemporaryDirectory(prefix="borough-summary-reproduction-") as temporary:
            isolated = Path(temporary)
            shutil.copytree(
                root / "src", isolated / "src", ignore=shutil.ignore_patterns("__pycache__")
            )
            for name in [
                "configs/default.toml",
                "configs/borough_uncertainty.toml",
                "uv.lock",
                *record["input_sha256"],
            ]:
                target = isolated / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(root / name, target)
            assert not (isolated / "data").exists() and not (isolated / "artifacts").exists()
            subprocess.run(
                [sys.executable, "-m", "nyc_mobility.cli", "borough-uncertainty"],
                cwd=isolated,
                env={**os.environ, "PYTHONPATH": str(isolated / "src")},
                capture_output=True,
                text=True,
                check=True,
            )
            repeated = json.loads(
                (isolated / "reports/latest_borough_uncertainty.json").read_text()
            )
            for key in [
                "comparisons",
                "protocol_sha256",
                "input_sha256",
                "source_hashes",
                "lockfile_sha256",
                "validation_days",
                "validation_rows",
                "model_names",
            ]:
                assert repeated[key] == record[key], key
            repeated_artifact = (
                isolated
                / "artifacts/borough_uncertainty"
                / repeated["uncertainty_id"]
                / "draws.npz"
            )
            with np.load(repeated_artifact, allow_pickle=False) as second:
                assert set(draws.files) == set(second.files)
                for key in draws.files:
                    np.testing.assert_array_equal(draws[key], second[key])
            repeated_csv = (
                isolated
                / "reports/borough_uncertainty"
                / repeated["uncertainty_id"]
                / "comparison.csv"
            )
            assert repeated_csv.read_bytes() == (directory / "comparison.csv").read_bytes()
    preserved = json.loads(preservation_record.read_text()) if preservation_record else {}
    for name, digest in preserved.items():
        assert sha256(root / name) == digest, f"Existing artifact changed: {name}"
    evidence = {
        "uncertainty_id": record["uncertainty_id"],
        "input_protocol_source_lock_hashes_match": True,
        "comparisons_independently_checked": len(comparisons),
        "maximum_percentile_discrepancy": largest_discrepancy,
        "isolated_summary_reproduction": True,
        "isolated_comparison_csv_identical": True,
        "isolated_draw_arrays_identical": True,
        "unchanged_files_sha256": preserved,
        "verification_models_fitted": 0,
        "test_metrics": None,
        "verification_script_sha256": sha256(Path(__file__)),
    }
    target = directory / "verification.json"
    if target.exists():
        raise FileExistsError("Preserve the existing verification report; use a new run directory")
    write_json(target, evidence)
    print(json.dumps(evidence, indent=2))
    return evidence


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report_directory", type=Path)
    parser.add_argument("--preservation-record", type=Path)
    args = parser.parse_args()
    verify(args.report_directory, args.preservation_record)
