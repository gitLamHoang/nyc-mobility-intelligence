"""Verify the committed browser evidence without raw data or model artifacts."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from nyc_mobility.data.download import sha256

ROOT = Path(__file__).resolve().parents[1]


def test_public_demo_is_sealed_to_complete_april_observations():
    data = json.loads((ROOT / "web/public/data/demo.json").read_text())
    report = json.loads((ROOT / "reports/demo_export.json").read_text())
    times = pd.DatetimeIndex([h["time"] for h in data["hours"]])
    expected = pd.date_range("2026-04-07T04:00Z", periods=48, freq="h")
    assert times.equals(expected)
    assert len(set(z["id"] for z in data["zones"])) == 262
    assert all(z["id"] not in {1, 264, 265} for z in data["zones"])
    values = np.asarray([h["values"] for h in data["hours"]])
    assert values.shape == (48, 262, 4)
    assert np.isfinite(values).all() and (values >= 0).all()
    assert report["rows"] == 12576 and report["models_fitted"] == 0
    assert report["test_metrics"] is None
    assert report["output_sha256"] == sha256(ROOT / "web/public/data/demo.json")
    assert report["provenance"] == data["provenance"]
    assert data["provenance"]["studySha256"] == sha256(
        ROOT / "reports/borough" / data["studyId"] / "metrics.json"
    )
    assert data["provenance"]["sqlSha256"] == sha256(ROOT / "sql/demo_summary.sql")


def test_sql_summary_reconciles_with_exported_zone_values():
    data = json.loads((ROOT / "web/public/data/demo.json").read_text())
    values = np.asarray([h["values"] for h in data["hours"]])
    for summary in data["boroughSummary"]:
        indices = [i for i, z in enumerate(data["zones"]) if z["borough"] == summary["borough"]]
        subset = values[:, indices, :]
        assert summary["zone_hours"] == subset.shape[0] * subset.shape[1]
        assert summary["recorded_pickups"] == subset[:, :, 0].sum()
        for column, metric in [(1, "temporal_mae"), (2, "borough_context_mae"), (3, "weekly_mae")]:
            # Public predictions are rounded to six decimals after SQL aggregation.
            assert summary[metric] == pytest.approx(
                np.abs(subset[:, :, 0] - subset[:, :, column]).mean(), abs=1e-6
            )
