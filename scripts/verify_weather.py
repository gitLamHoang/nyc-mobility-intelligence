"""Independently verify weather as-of joins and reproduce outputs in an isolated directory."""

import json
import shutil
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from nyc_mobility.config import write_json
from nyc_mobility.data.download import sha256
from nyc_mobility.data.weather import audit_weather
from nyc_mobility.features.weather import WEATHER_VALUES


def main() -> None:
    root = Path.cwd()
    record = json.loads((root / "reports/latest_weather.json").read_text())
    output = root / "reports/weather" / record["weather_id"]
    artifact = root / "artifacts/weather" / record["weather_id"]
    for file, expected in {
        **record["input_source_lock_hashes"],
        **record["outputs_sha256"],
    }.items():
        assert sha256(root / file) == expected, file
    obs = pd.read_parquet(artifact / "observations.parquet")
    snapshots = pd.read_parquet(artifact / "snapshots.parquet")
    checked = 0
    for (station, delay), group in snapshots.groupby(["station_id", "delay_hours"]):
        source = obs.loc[obs.station_id.eq(station)].sort_values("observed_at")
        hours = pd.DatetimeIndex(group.hour)
        times = pd.DatetimeIndex(source.observed_at)
        indices = times.searchsorted(hours - pd.Timedelta(hours=delay), side="left") - 1
        valid = indices >= 0
        bounded = np.maximum(indices, 0)
        selected = times[bounded]
        valid &= (hours - selected) <= pd.Timedelta(hours=record["policy"]["max_age_hours"])
        expected_times = pd.Series(selected, index=group.index).where(valid)
        pd.testing.assert_series_equal(group.observed_at, expected_times, check_names=False)
        expected_values = source[WEATHER_VALUES].to_numpy()[bounded].copy()
        expected_values[~valid] = np.nan
        np.testing.assert_allclose(group[WEATHER_VALUES], expected_values, rtol=0, atol=0)
        expected_available = expected_times + pd.Timedelta(hours=delay)
        pd.testing.assert_series_equal(
            group.assumed_available_at, expected_available, check_names=False
        )
        age = (group.hour - expected_times) / pd.Timedelta(hours=1)
        np.testing.assert_allclose(group.age_hours, age, rtol=0, atol=0)
        assert (group.loc[valid, "assumed_available_at"] < group.loc[valid, "hour"]).all()
        checked += len(group)
    # Only weather snapshots, source/config and lock are exposed; no taxi data or models.
    with tempfile.TemporaryDirectory(prefix="nyc-weather-") as directory:
        isolated = Path(directory)
        shutil.copytree(root / "src", isolated / "src")
        shutil.copytree(root / "configs", isolated / "configs")
        shutil.copy(root / "uv.lock", isolated / "uv.lock")
        weather = isolated / "data/external/weather"
        weather.parent.mkdir(parents=True)
        weather.symlink_to(root / "data/external/weather", target_is_directory=True)
        reproduced = audit_weather(record["config"], root=isolated)
        expected = {Path(file).name: value for file, value in record["outputs_sha256"].items()}
        actual = {Path(file).name: value for file, value in reproduced["outputs_sha256"].items()}
        assert actual == expected
    previous = json.loads(
        (root / "reports/borough_uncertainty/20260925T190813Z-72c52e/verification.json").read_text()
    )["unchanged_files_sha256"]
    previous["reports/latest_borough_uncertainty.json"] = sha256(
        root / "reports/borough_uncertainty/20260925T190813Z-72c52e/metrics.json"
    )
    for file, expected in previous.items():
        assert sha256(root / file) == expected, file
    verification = {
        "weather_id": record["weather_id"],
        "input_source_lock_output_hashes_match": True,
        "independent_searchsorted_snapshot_rows_checked": checked,
        "isolated_weather_only_reproduction": True,
        "all_three_csv_and_two_parquet_outputs_byte_identical": True,
        "unchanged_files_sha256": previous,
        "models_fitted": 0,
        "test_metrics": None,
        "verification_script_sha256": sha256(Path(__file__)),
    }
    write_json(output / "verification.json", verification)
    print(f"Verified {checked:,} station/target/delay rows, isolated outputs and 20 prior files")


if __name__ == "__main__":
    main()
