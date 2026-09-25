"""Paired uncertainty for three frozen borough contrasts, using published daily errors."""

import json
import subprocess
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd

from nyc_mobility.config import write_json
from nyc_mobility.data.download import sha256
from nyc_mobility.evaluation.uncertainty import (
    bootstrap_mae,
    family_comparisons,
    validate_daily_errors,
)

CONTRASTS = [
    {"candidate": "borough_static", "reference": "hist_gradient_boosting"},
    {"candidate": "borough_context", "reference": "hist_gradient_boosting"},
    {"candidate": "borough_context", "reference": "borough_static"},
]


def validate_protocol(protocol: dict) -> list[int]:
    study = protocol["study"]
    if study["method"] != "fold-stratified-circular-day-blocks":
        raise ValueError("Unsupported uncertainty method")
    if (
        protocol["contrasts"] != CONTRASTS
        or type(study["family_size"]) is not int
        or study["family_size"] != len(CONTRASTS)
        or study["family_method"] != "bonferroni"
        or study["family_metric"] != "delta_mae"
    ):
        raise ValueError("The family must contain all three frozen borough MAE contrasts")
    levels = [study["confidence_level"], study["family_confidence_level"]]
    if any(isinstance(v, bool) or not 0 < v < 1 for v in levels) or levels[0] != levels[1]:
        raise ValueError("Marginal and family confidence must match and be between zero and one")
    blocks = [study["primary_block_days"], *study["sensitivity_block_days"]]
    if (
        any(type(b) is not int or b <= 0 for b in blocks)
        or len(blocks) != 3
        or len(set(blocks)) != len(blocks)
    ):
        raise ValueError("Provide three unique positive integer block lengths")
    if type(study["replicates"]) is not int or study["replicates"] < 2:
        raise ValueError("At least two bootstrap replicates are required")
    if type(study["random_seed"]) is not int or study["random_seed"] < 0:
        raise ValueError("Random seed must be a nonnegative integer")
    return blocks


def run_borough_uncertainty(
    config: dict,
    root: Path = Path("."),
    protocol_path: Path = Path("configs/borough_uncertainty.toml"),
) -> dict:
    path = protocol_path if protocol_path.is_absolute() else root / protocol_path
    protocol_hash = sha256(path)
    source_paths = sorted((root / "src").rglob("*.py"))
    source_hashes = {str(p.relative_to(root)): sha256(p) for p in source_paths}
    lock_hash = sha256(root / "uv.lock")
    protocol = tomllib.loads(path.read_text())
    blocks = validate_protocol(protocol)
    study = protocol["study"]
    source = root / "reports/borough" / study["borough_id"]
    paths = [source / "metrics.json", source / "daily_mae.csv"]
    hashes = [study["metrics_sha256"], study["daily_mae_sha256"]]
    for p, expected in zip(paths, hashes, strict=True):
        if sha256(p) != expected:
            raise ValueError(f"Uncertainty input hash mismatch: {p.name}")
    record = json.loads(paths[0].read_text())
    if record["borough_id"] != study["borough_id"]:
        raise ValueError("borough source identifier differs from protocol")
    names, folds = validate_daily_errors(
        pd.read_csv(paths[1]), record, config["split"]["test_start"]
    )
    if any(name not in names for pair in CONTRASTS for name in pair.values()):
        raise ValueError("Source is missing a required borough comparison model")
    if max(blocks) > min(len(weights) for weights, _ in folds):
        raise ValueError("Block length cannot exceed a fold's day count")
    point = np.array([record["pooled_metrics"][name]["mae"] for name in names])
    results, draws = [], {}
    for block in blocks:
        sample = bootstrap_mae(folds, block, study["replicates"], study["random_seed"])
        draws[f"block_{block}_mae"] = sample
        results.extend(
            {
                "block_days": block,
                "role": "primary" if block == study["primary_block_days"] else "sensitivity",
                "confidence_level": study["confidence_level"],
                **result,
            }
            for result in family_comparisons(sample, point, names, protocol)
        )
    for p, expected in zip([path, *paths], [protocol_hash, *hashes], strict=True):
        if sha256(p) != expected:
            raise ValueError("Protocol or input changed during resampling")
    if (
        source_hashes
        != {str(p.relative_to(root)): sha256(p) for p in sorted((root / "src").rglob("*.py"))}
        or sha256(root / "uv.lock") != lock_hash
    ):
        raise ValueError("Source or dependency lock changed during resampling")
    identifier = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:6]
    output = root / "reports/borough_uncertainty" / identifier
    artifact = root / "artifacts/borough_uncertainty" / identifier
    output.mkdir(parents=True, exist_ok=False)
    artifact.mkdir(parents=True, exist_ok=False)
    np.savez_compressed(artifact / "draws.npz", model_names=np.array(names), **draws)
    pd.DataFrame(results).to_csv(output / "comparison.csv", index=False)
    result = {
        "uncertainty_id": identifier,
        "created_at": datetime.now(UTC).isoformat(),
        "protocol": protocol,
        "protocol_sha256": protocol_hash,
        "input_sha256": {str(p.relative_to(root)): sha256(p) for p in paths},
        "source_hashes": source_hashes,
        "lockfile_sha256": lock_hash,
        "draws_sha256": sha256(artifact / "draws.npz"),
        "git_revision": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False
        ).stdout.strip(),
        "git_worktree_dirty": bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            ).stdout.strip()
        ),
        "validation_days": sum(len(weights) for weights, _ in folds),
        "validation_rows": record["validation_rows"],
        "model_names": names,
        "comparisons": results,
        "quantile_method": "linear",
        "models_refitted": 0,
        "target_tables_read": 0,
        "scope": "Fixed February–April development errors; sparse/zero-demand harm remains.",
        "serving_model_changed": False,
        "test_metrics": None,
        "interpretation": "Nominal Bonferroni family covers three MAE differences per block "
        "setting, conditional on the bootstrap approximation and fixed development models. "
        "Relative intervals are marginal. No coverage across settings, all prior model "
        "selection or future periods is claimed.",
    }
    write_json(output / "metrics.json", result)
    write_json(root / "reports/latest_borough_uncertainty.json", result)
    print(f"Completed paired borough uncertainty {identifier}", flush=True)
    print(pd.DataFrame(results).to_string(index=False), flush=True)
    return result
