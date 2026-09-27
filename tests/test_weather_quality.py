"""Synthetic tests for the separate source-specific unverified-weather sensitivity."""

import json

import numpy as np
import pandas as pd
import pytest

from nyc_mobility.data.weather import (
    AUDIT_FIELDS,
    FIELDS,
    LEGACY_QUALITY_POLICY,
    UNVERIFIED_QUALITY_POLICY,
    audit_weather,
    parse_observations,
    snapshot_quality,
)
from nyc_mobility.features.weather import WEATHER_VALUES, weather_snapshots

STATION = {"id": "SYNTHETIC_NYC", "latitude": 40.78, "longitude": -73.97}
START = pd.Timestamp("2026-04-30T04:00:00Z")
END = pd.Timestamp("2026-05-01T04:00:00Z")


def observation(date="2026-04-30T12:30:00", source="413", report="FM15", **changes):
    row = {
        "STATION": STATION["id"],
        "DATE": date,
        "LATITUDE": STATION["latitude"],
        "LONGITUDE": STATION["longitude"],
        "temperature": -2.3,
        "dew_point_temperature": -7.1,
        "wind_speed": 2.8,
        "precipitation": 0.2,
    }
    for field in AUDIT_FIELDS:
        row.update(
            {
                field + "_Source_Code": source,
                field + "_Quality_Code": "1" if source == "223" else "",
                field + "_Measurement_Code": "N"
                if source == "223" and field == "wind_speed"
                else "",
                field + "_Report_Type": report,
            }
        )
    return {**row, **changes}


def parse(rows):
    return parse_observations(
        pd.DataFrame(rows), STATION, START, END, quality_policy=UNVERIFIED_QUALITY_POLICY
    )


@pytest.mark.parametrize(
    "source, report, accepted",
    [
        ("412", "FM12", ["temperature_c", "dew_point_c"]),
        ("412", "FM94_1", ["temperature_c", "dew_point_c"]),
        ("413", "FM15", WEATHER_VALUES),
        ("413", "FM16", WEATHER_VALUES),
    ],
)
def test_additional_sources_have_unverified_values_and_separate_counts(source, report, accepted):
    clean, audit = parse([observation(source=source, report=report)])
    for variable in WEATHER_VALUES:
        assert clean.loc[0, variable + "_source"] == source
        if variable in accepted:
            assert pd.notna(clean.loc[0, variable])
            assert clean.loc[0, variable + "_quality"] == "unverified"
        else:
            assert pd.isna(clean.loc[0, variable])
            assert clean.loc[0, variable + "_quality"] == "rejected"
    assert audit.accepted_good.sum() == 0
    assert audit.accepted_unverified.sum() == len(accepted)
    assert audit.accepted.sum() == len(accepted)
    assert audit.loc[audit.variable.eq("precipitation"), "accepted"].item() == 0


@pytest.mark.parametrize("source, report", [("412", "FM12"), ("413", "FM15")])
@pytest.mark.parametrize("field", list(FIELDS))
@pytest.mark.parametrize("flag", ["1", "0", "2", " ", "unknown"])
def test_nonblank_quality_never_borrows_another_sources_quality_mapping(
    source, report, field, flag
):
    clean, audit = parse(
        [observation(source=source, report=report, **{field + "_Quality_Code": flag})]
    )
    assert pd.isna(clean.loc[0, FIELDS[field]])
    assert clean.loc[0, FIELDS[field] + "_quality"] == "rejected"
    affected = audit.loc[audit.variable.eq(field)].iloc[0]
    assert affected.accepted_good == affected.accepted_unverified == affected.accepted == 0
    assert affected.policy_excluded == 1


@pytest.mark.parametrize("field", list(FIELDS))
@pytest.mark.parametrize("flag", ["C", "N", "V", " ", "unknown"])
def test_nonblank_measurement_flags_are_not_guessed_for_new_sources(field, flag):
    clean, _ = parse([observation(**{field + "_Measurement_Code": flag})])
    assert clean.loc[0, FIELDS[field] + "_quality"] == "rejected"


@pytest.mark.parametrize(
    "source, report", [("412", "FM15"), ("413", "FM12"), ("999", "FM15"), ("413", "FM99")]
)
def test_sources_and_reports_must_match_the_exact_documented_policy(source, report):
    clean, audit = parse([observation(source=source, report=report)])
    assert clean[WEATHER_VALUES].isna().all().all()
    assert clean[[v + "_quality" for v in WEATHER_VALUES]].eq("rejected").all().all()
    assert audit.accepted.sum() == 0


def test_per_value_source_quality_missing_and_rejection_stay_distinct():
    rows = [
        observation(
            source="223",
            temperature=np.nan,
            dew_point_temperature_Source_Code="413",
            dew_point_temperature_Quality_Code="",
            wind_speed=-1,
        ),
        observation("2026-04-30T13:30:00", source="223"),
    ]
    clean, audit = parse(rows)
    assert clean.temperature_c_quality.tolist() == ["missing", "good"]
    assert clean.temperature_c_source.tolist() == ["223", "223"]
    assert clean.dew_point_c_quality.tolist() == ["unverified", "good"]
    assert clean.dew_point_c_source.tolist() == ["413", "223"]
    assert clean.wind_speed_m_s_quality.tolist() == ["rejected", "good"]
    assert audit.accepted.sum() == audit.accepted_good.sum() + audit.accepted_unverified.sum()
    assert audit.accepted_good.sum() == 3
    assert audit.accepted_unverified.sum() == 1


@pytest.mark.parametrize("wind, quality", [(-0.1, "rejected"), (0, "unverified")])
def test_new_wind_requires_nonnegative_measurement(wind, quality):
    clean, _ = parse([observation(wind_speed=wind)])
    assert clean.wind_speed_m_s_quality.item() == quality


def test_explicit_legacy_policy_and_default_keep_the_original_schema_and_decisions():
    raw = pd.DataFrame([observation(source="223"), observation("2026-04-30T13:30:00")])
    default, default_audit = parse_observations(raw, STATION, START, END)
    explicit, explicit_audit = parse_observations(
        raw, STATION, START, END, quality_policy=LEGACY_QUALITY_POLICY
    )
    pd.testing.assert_frame_equal(default, explicit)
    pd.testing.assert_frame_equal(default_audit, explicit_audit)
    assert default.columns.tolist() == ["station_id", "observed_at", *WEATHER_VALUES]
    assert default_audit.columns.tolist() == [
        "month",
        "source",
        "quality",
        "measurement",
        "report_type",
        "station_id",
        "variable",
        "rows",
        "present",
        "accepted",
        "policy_excluded",
    ]
    assert default.loc[0, WEATHER_VALUES].notna().all()
    assert default.loc[1, WEATHER_VALUES].isna().all()


def test_unknown_policy_fails_before_parsing():
    with pytest.raises(ValueError, match="Unsupported weather quality policy"):
        parse_observations(pd.DataFrame(), STATION, START, END, quality_policy="permissive")


def test_snapshot_flags_follow_selected_row_and_do_not_backfill_good_metadata():
    clean, _ = parse(
        [
            observation("2026-04-30T12:30:00", source="223"),
            observation("2026-04-30T13:30:00", temperature=np.nan, wind_speed_Quality_Code="1"),
        ]
    )
    targets = pd.DatetimeIndex(
        [
            "2026-04-30T12:00:00Z",
            "2026-04-30T13:00:00Z",
            "2026-04-30T14:00:00Z",
            "2026-04-30T20:00:00Z",
        ]
    )
    selected = weather_snapshots(clean, targets, delay_hours=0, max_age_hours=6)
    result = snapshot_quality(selected, clean)
    assert result.temperature_c_quality.tolist() == ["missing", "good", "missing", "missing"]
    assert result.temperature_c_source.tolist() == ["", "223", "413", ""]
    assert result.dew_point_c_quality.tolist() == ["missing", "good", "unverified", "missing"]
    assert result.wind_speed_m_s_quality.tolist() == ["missing", "good", "rejected", "missing"]
    pd.testing.assert_frame_equal(result[selected.columns], selected)


def test_snapshot_metadata_joins_by_station_and_rejects_ambiguous_keys():
    clean, _ = parse([observation()])
    second = clean.copy()
    second["station_id"] = "OTHER_SYNTHETIC"
    second["temperature_c_source"] = "SENTINEL"
    combined = pd.concat([clean, second], ignore_index=True)
    targets = pd.DatetimeIndex(["2026-04-30T13:00:00Z"])
    selected = weather_snapshots(combined, targets, 0)
    result = snapshot_quality(selected, combined)
    assert result.temperature_c_source.tolist() == ["413", "SENTINEL"]
    with pytest.raises(pd.errors.MergeError, match="not a many-to-one"):
        snapshot_quality(selected, pd.concat([combined, clean], ignore_index=True))


def test_sensitivity_audit_has_separate_artifacts_flags_and_no_legacy_overwrite(
    tmp_path, monkeypatch
):
    import nyc_mobility.data.weather as module

    source = tmp_path / "data/external/synthetic.parquet"
    source.parent.mkdir(parents=True)
    pd.DataFrame(
        [
            observation("2026-04-30T12:30:00", source="223"),
            observation("2026-04-30T13:30:00"),
        ]
    ).to_parquet(source, index=False)
    (tmp_path / "uv.lock").write_text("synthetic dependency lock")
    reports = tmp_path / "reports"
    reports.mkdir()
    legacy = reports / "latest_weather.json"
    legacy.write_text("historical report sentinel")
    spec = tmp_path / "weather-policy.toml"
    spec.write_text(f'''[window]
start = "2026-04-30T04:00:00Z"
end = "2026-05-01T04:00:00Z"
[policy]
quality = "{UNVERIFIED_QUALITY_POLICY}"
delays_hours = [0, 1, 3, 6]
max_age_hours = 6
[[stations]]
id = "{STATION["id"]}"
latitude = {STATION["latitude"]}
longitude = {STATION["longitude"]}
[[assets]]
file = "data/external/synthetic.parquet"
url = "https://example.invalid/synthetic.parquet"
sha256 = "{module.sha256(source)}"
station_id = "{STATION["id"]}"
''')
    monkeypatch.setattr(
        module,
        "fetch",
        lambda url, destination: {
            "url": url,
            "file": str(destination),
            "sha256": module.sha256(destination),
        },
    )
    config = {"split": {"train_start": "2025-12-01", "test_start": "2026-05-01"}}
    result = audit_weather(config, tmp_path, spec)
    assert legacy.read_text() == "historical report sentinel"
    assert not (reports / "weather").exists()
    assert not (tmp_path / "artifacts/weather").exists()
    saved = json.loads((reports / "latest_weather_policy.json").read_text())
    assert saved["weather_id"] == result["weather_id"]
    assert saved["policy"]["quality"] == UNVERIFIED_QUALITY_POLICY
    assert result["models_fitted"] == 0 and result["test_metrics"] is None
    assert result["eligible_for_point_in_time_model_claim"] is False
    assert result["historical_publication_times_verified"] is False
    output = reports / "weather_policy" / result["weather_id"]
    flags = pd.read_csv(output / "quality_flags.csv")
    assert flags.accepted_good.sum() == 3 and flags.accepted_unverified.sum() == 3
    native = pd.read_csv(output / "native_coverage.csv")
    assert native.accepted_good_values.eq(1).all()
    assert native.accepted_unverified_values.eq(1).all()
    coverage = pd.read_csv(output / "availability_coverage.csv")
    zero = coverage.loc[coverage.delay_hours.eq(0)].iloc[0]
    assert zero.complete_hours == 7
    assert zero.complete_good_hours == 1
    assert zero.complete_unverified_hours == 6
    for variable in WEATHER_VALUES:
        assert zero[variable + "_good_hours"] == 1
        assert zero[variable + "_unverified_hours"] == 6
    artifacts = tmp_path / "artifacts/weather_policy" / result["weather_id"]
    snapshot = pd.read_parquet(artifacts / "snapshots.parquet")
    unmatched = snapshot.observed_at.isna()
    assert snapshot.loc[unmatched, "temperature_c_quality"].eq("missing").all()
    assert snapshot.loc[unmatched, "temperature_c_source"].eq("").all()
