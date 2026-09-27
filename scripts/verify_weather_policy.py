"""Check unverified quality propagation, replay both policies, and preserve prior evidence."""

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


def same_outputs(left, right):
    expected = {Path(p).name: h for p, h in left["outputs_sha256"].items()}
    actual = {Path(p).name: h for p, h in right["outputs_sha256"].items()}
    assert expected == actual


def main():
    root = Path.cwd()
    record = json.loads((root / "reports/latest_weather_policy.json").read_text())
    legacy = json.loads((root / "reports/latest_weather.json").read_text())
    prepared = json.loads((root / "reports/latest_weather_features.json").read_text())
    for r in (record, prepared):
        for p, h in {**r["input_source_lock_hashes"], **r["outputs_sha256"]}.items():
            assert sha256(root / p) == h, p
    artifact = root / "artifacts/weather_policy" / record["weather_id"]
    observations = pd.read_parquet(artifact / "observations.parquet")
    snapshots = pd.read_parquet(artifact / "snapshots.parquet")
    checked = 0
    for (station, delay), group in snapshots.groupby(["station_id", "delay_hours"]):
        source = observations.loc[observations.station_id.eq(station)].sort_values("observed_at")
        hours, times = pd.DatetimeIndex(group.hour), pd.DatetimeIndex(source.observed_at)
        indices = times.searchsorted(hours - pd.Timedelta(int(delay), unit="h"), side="left") - 1
        valid = indices >= 0
        bounded = np.maximum(indices, 0)
        chosen = times[bounded]
        valid &= (hours - chosen) <= pd.Timedelta(12, unit="h")
        expected_times = pd.Series(chosen, index=group.index).where(valid)
        pd.testing.assert_series_equal(group.observed_at, expected_times, check_names=False)
        expected_available = expected_times + pd.Timedelta(int(delay), unit="h")
        pd.testing.assert_series_equal(
            group.assumed_available_at, expected_available, check_names=False
        )
        np.testing.assert_allclose(
            group.age_hours,
            (group.hour - expected_times) / pd.Timedelta(1, unit="h"),
            rtol=0,
            atol=0,
        )
        expected = source[WEATHER_VALUES].to_numpy()[bounded].copy()
        expected[~valid] = np.nan
        np.testing.assert_allclose(group[WEATHER_VALUES], expected, rtol=0, atol=0)
        for value in WEATHER_VALUES:
            for suffix, absent in (("_quality", "missing"), ("_source", "")):
                column = value + suffix
                expected = source[column].to_numpy()[bounded].copy()
                expected[~valid] = absent
                np.testing.assert_array_equal(group[column], expected)
        checked += len(group)
    # Replay original and versioned policies without exposing any taxi target or model files.
    with tempfile.TemporaryDirectory(prefix="nyc-weather-policy-") as temporary:
        isolated = Path(temporary)
        for directory in ("src", "configs"):
            shutil.copytree(root / directory, isolated / directory)
        shutil.copy(root / "uv.lock", isolated / "uv.lock")
        (isolated / "data/external").mkdir(parents=True)
        (isolated / "data/external/weather").symlink_to(root / "data/external/weather")
        for spec, original in (("weather_inputs.toml", legacy), ("weather_inputs_v2.toml", record)):
            reproduced = audit_weather(
                record["config"], root=isolated, spec_path=Path("configs") / spec
            )
            same_outputs(original, reproduced)
    feature_values = 0
    for delay in (3, 6):
        bundle = pd.read_parquet(
            root
            / "artifacts/weather_features"
            / prepared["preparation_id"]
            / f"delay_{delay}.parquet"
        ).set_index("hour")
        selected = snapshots.loc[snapshots.delay_hours.eq(delay)]
        for station, alias in (
            ("USW00014732", "lga"),
            ("USW00094789", "jfk"),
            ("USW00094728", "cp"),
        ):
            data = selected.loc[selected.station_id.eq(station)].set_index("hour").loc[bundle.index]
            for value in WEATHER_VALUES:
                prefix = f"weather_{alias}_{value}"
                np.testing.assert_allclose(bundle[prefix], data[value], rtol=0, atol=0)
                np.testing.assert_array_equal(bundle[prefix + "_missing"], data[value].isna())
                np.testing.assert_array_equal(
                    bundle[prefix + "_unverified"], data[value + "_quality"].eq("unverified")
                )
                feature_values += len(bundle) * 3
            np.testing.assert_allclose(bundle[f"weather_{alias}_age_hours"], data.age_hours)
            feature_values += len(bundle)
    previous = json.loads(
        (root / "reports/weather" / legacy["weather_id"] / "verification.json").read_text()
    )["unchanged_files_sha256"]
    previous.update(legacy["outputs_sha256"])
    previous["reports/latest_weather.json"] = sha256(
        root / "reports/weather" / legacy["weather_id"] / "metrics.json"
    )
    # The v1 specification and policy are pinned separately in the new comparison protocol.
    for file in ("configs/weather_inputs.toml", "docs/WEATHER_SOURCE_POLICY.md"):
        expected = prepared["protocol"]["weather"][
            "legacy_spec_sha256" if file.endswith("toml") else "legacy_policy_sha256"
        ]
        previous[file] = expected
    for p, h in previous.items():
        assert sha256(root / p) == h, p
    result = {
        "weather_id": record["weather_id"],
        "preparation_id": prepared["preparation_id"],
        "independent_snapshot_rows_checked": checked,
        "independent_bundle_values_checked": feature_values,
        "legacy_and_new_policy_isolated_outputs_byte_identical": True,
        "unchanged_files_sha256": previous,
        "models_fitted": 0,
        "test_metrics": None,
        "verification_script_sha256": sha256(Path(__file__)),
    }
    write_json(
        root / "reports/weather_features" / prepared["preparation_id"] / "verification.json", result
    )
    print(
        f"Verified {checked:,} snapshots, {feature_values:,} bundle values "
        f"and {len(previous)} preserved files"
    )


if __name__ == "__main__":
    main()
