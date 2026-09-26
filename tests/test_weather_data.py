"""Synthetic GHCNh rows exercise parsing policy; no actual weather data is needed in CI."""

import json

import numpy as np
import pandas as pd
import pytest

from nyc_mobility.data.weather import (
    AUDIT_FIELDS,
    FIELDS,
    longest_missing_run,
    parse_observations,
)

STATION = {"id": "SYNTHETIC_NYC", "latitude": 40.78, "longitude": -73.97}
START = pd.Timestamp("2026-04-30T04:00:00Z")
END = pd.Timestamp("2026-05-01T04:00:00Z")  # May 1 midnight in New York.


def observation(date="2026-04-30T12:30:00", **changes):
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
                field + "_Source_Code": "223",
                field + "_Quality_Code": "1",
                field + "_Measurement_Code": "N" if field == "wind_speed" else "",
                field + "_Report_Type": "FM15",
            }
        )
    return {**row, **changes}


def parse(rows):
    return parse_observations(pd.DataFrame(rows), STATION, START, END)


def test_values_are_already_scaled_and_negative_temperatures_are_valid():
    clean, audit = parse([observation()])
    assert clean.loc[0, "temperature_c"] == -2.3
    assert clean.loc[0, "dew_point_c"] == -7.1
    assert clean.loc[0, "wind_speed_m_s"] == 2.8
    assert clean.loc[0, "observed_at"] == pd.Timestamp("2026-04-30T12:30:00Z")
    assert clean.loc[0, "station_id"] == STATION["id"]
    assert set(clean) == {"station_id", "observed_at", *FIELDS.values()}
    assert audit.set_index("variable").loc[list(FIELDS), "accepted"].eq(1).all()


def test_half_open_bounds_precede_measurement_identity_and_duplicate_validation():
    poison = {
        "temperature": "DO NOT PARSE",
        "dew_point_temperature": "DO NOT PARSE",
        "wind_speed": "DO NOT PARSE",
        "precipitation": "DO NOT PARSE",
        "STATION": "WRONG STATION",
        "LATITUDE": "DO NOT PARSE",
        "LONGITUDE": "DO NOT PARSE",
    }
    before = observation("2026-04-30T03:59:59", **poison)
    after = observation("2026-05-01T04:00:00", **poison)
    clean, audit = parse(
        [
            before,
            observation("2026-04-30T04:00:00"),
            observation("2026-05-01T03:59:59"),
            after,
            after,
        ]
    )
    assert clean.observed_at.dt.strftime("%Y-%m-%dT%H:%M:%SZ").tolist() == [
        "2026-04-30T04:00:00Z",
        "2026-05-01T03:59:59Z",
    ]
    assert audit.rows.sum() == 2 * len(AUDIT_FIELDS)
    assert set(audit.month) == {"2026-04"}  # The last valid UTC row still belongs to NYC April.


def test_excluded_tail_cannot_change_clean_values_or_flag_counts():
    source = [observation(), observation("2026-04-30T13:30:00", temperature=-3.5)]
    expected, expected_audit = parse(source)
    changed, changed_audit = parse(
        [*source, observation("2026-05-15T12:30:00", temperature="not numeric")]
    )
    pd.testing.assert_frame_equal(changed, expected)
    pd.testing.assert_frame_equal(changed_audit, expected_audit)


@pytest.mark.parametrize("code", ["412", "413"])
def test_later_sources_with_blank_quality_are_explicit_policy_exclusions(code):
    rejected = observation("2026-04-30T13:30:00")
    for field in FIELDS:
        rejected[field + "_Source_Code"] = code
        rejected[field + "_Quality_Code"] = ""
    clean, audit = parse([observation(), rejected])
    assert clean.loc[0, list(FIELDS.values())].notna().all()
    assert clean.loc[1, list(FIELDS.values())].isna().all()
    rejected_audit = audit.loc[audit.source.eq(code)]
    assert set(rejected_audit.variable) == set(FIELDS)
    assert rejected_audit.present.eq(1).all()
    assert rejected_audit.accepted.eq(0).all()
    assert rejected_audit.policy_excluded.eq(1).all()


@pytest.mark.parametrize("field", list(FIELDS))
@pytest.mark.parametrize(
    "flag, value",
    [
        ("Source_Code", "412"),
        ("Source_Code", "413"),
        ("Quality_Code", ""),
        ("Quality_Code", None),
        ("Quality_Code", "0"),
        ("Quality_Code", "2"),
        ("Report_Type", "FM99"),
    ],
)
def test_quality_source_and_report_policy_is_per_value_not_per_row(field, flag, value):
    clean, audit = parse([observation(**{field + "_" + flag: value})])
    assert pd.isna(clean.loc[0, FIELDS[field]])
    others = [name for key, name in FIELDS.items() if key != field]
    assert clean.loc[0, others].notna().all()
    affected = audit.loc[audit.variable.eq(field)].iloc[0]
    assert affected.present == 1 and affected.accepted == 0 and affected.policy_excluded == 1


@pytest.mark.parametrize("report", ["FM12", "FM15", "FM16"])
def test_documented_reports_are_accepted(report):
    row = observation()
    for field in FIELDS:
        row[field + "_Report_Type"] = report
    clean, _ = parse([row])
    assert clean[list(FIELDS.values())].notna().all().all()


@pytest.mark.parametrize("code", ["C", "N", "V"])
def test_documented_wind_measurement_codes_are_accepted(code):
    clean, _ = parse([observation(wind_speed_Measurement_Code=code, wind_speed=0.0)])
    assert clean.loc[0, "wind_speed_m_s"] == 0.0


@pytest.mark.parametrize("code", ["", None, "9", "X"])
def test_unsupported_wind_codes_are_not_guessed(code):
    clean, audit = parse([observation(wind_speed_Measurement_Code=code)])
    assert pd.isna(clean.loc[0, "wind_speed_m_s"])
    row = audit.loc[audit.variable.eq("wind_speed")].iloc[0]
    assert row.policy_excluded == 1


def test_negative_wind_is_excluded_but_negative_temperature_is_kept():
    clean, audit = parse([observation(wind_speed=-1.0)])
    assert pd.isna(clean.loc[0, "wind_speed_m_s"])
    assert clean.loc[0, "temperature_c"] == -2.3
    assert audit.loc[audit.variable.eq("wind_speed"), "policy_excluded"].item() == 1


@pytest.mark.parametrize("field", ["temperature", "dew_point_temperature"])
def test_undocumented_temperature_measurement_flags_are_not_interpreted(field):
    clean, audit = parse([observation(**{field + "_Measurement_Code": "A"})])
    assert pd.isna(clean.loc[0, FIELDS[field]])
    assert audit.loc[audit.variable.eq(field), "policy_excluded"].item() == 1


def test_missing_values_and_excluded_values_are_counted_separately_without_imputation():
    missing = observation("2026-04-30T13:30:00", temperature=np.nan)
    rejected = observation("2026-04-30T14:30:00", temperature_Quality_Code="2")
    clean, audit = parse([observation(), missing, rejected])
    assert clean.temperature_c.iloc[0] == -2.3
    assert clean.temperature_c.iloc[1:].isna().all()
    group = audit.loc[audit.variable.eq("temperature")]
    assert group.rows.sum() == 3
    assert group.present.sum() == 2
    assert group.accepted.sum() == 1
    assert group.policy_excluded.sum() == 1


def test_precipitation_is_audited_only_even_for_zero_and_trace_measurements():
    rows = [observation(precipitation=0.0), observation("2026-04-30T13:30:00", precipitation=0.2)]
    rows[1]["precipitation_Measurement_Code"] = "T"
    clean, audit = parse(rows)
    assert "precipitation" not in clean and "precipitation_mm" not in clean
    groups = audit.loc[audit.variable.eq("precipitation")]
    assert groups.accepted.sum() == 0
    assert groups.present.sum() == 2
    assert groups.policy_excluded.sum() == 2


def test_precipitation_only_rows_do_not_replace_a_core_weather_observation():
    precip_only = observation(
        "2026-04-30T13:30:00", temperature=np.nan, dew_point_temperature=np.nan, wind_speed=np.nan
    )
    clean, audit = parse([observation(), precip_only])
    assert len(clean) == 1
    assert audit.loc[audit.variable.eq("precipitation"), "present"].sum() == 2


@pytest.mark.parametrize(
    "change, message",
    [
        ({"STATION": "WRONG"}, "identity"),
        ({"LATITUDE": 41.0}, "coordinates"),
        ({"LONGITUDE": -73.0}, "coordinates"),
        ({"LATITUDE": np.nan}, "coordinates"),
        ({"LONGITUDE": np.inf}, "coordinates"),
    ],
)
def test_identity_and_geography_must_match_station(change, message):
    with pytest.raises(ValueError, match=message):
        parse([observation(**change)])


def test_duplicates_fail_instead_of_arbitrary_deduplication():
    with pytest.raises(ValueError, match="Duplicate"):
        parse([observation(), observation(temperature=7.0)])


@pytest.mark.parametrize("field", AUDIT_FIELDS)
@pytest.mark.parametrize("value", [np.inf, -np.inf, "bad number"])
def test_non_numeric_or_infinite_development_values_fail(field, value):
    with pytest.raises(ValueError):
        parse([observation(**{field: value})])


@pytest.mark.parametrize(
    "date", [None, "2026-04-30", "2026-04-30T12:30:00Z", "2026-04-31T12:30:00"]
)
def test_malformed_or_impossible_development_dates_fail(date):
    with pytest.raises(ValueError):
        parse([observation(date)])


def test_empty_development_window_fails():
    with pytest.raises(ValueError, match="No development"):
        parse([observation("2026-05-01T04:00:00")])


@pytest.mark.parametrize(
    "start, end",
    [(START.tz_localize(None), END), (START, END.tz_convert("America/New_York")), (END, START)],
)
def test_bounds_require_utc_and_increasing_order(start, end):
    with pytest.raises(ValueError):
        parse_observations(pd.DataFrame([observation()]), STATION, start, end)


def test_required_flag_column_cannot_be_silently_defaulted():
    raw = pd.DataFrame([observation()]).drop(columns="temperature_Quality_Code")
    with pytest.raises(ValueError, match="Missing required"):
        parse_observations(raw, STATION, START, END)


def test_unsorted_indexed_input_is_sorted_without_misaligning_values():
    raw = pd.DataFrame(
        [observation("2026-04-30T13:30:00", temperature=9.0), observation()], index=[11, 4]
    )
    clean, _ = parse_observations(raw, STATION, START, END)
    assert clean.temperature_c.tolist() == [-2.3, 9.0]
    assert clean.observed_at.is_monotonic_increasing


@pytest.mark.parametrize(
    "values, expected",
    [
        ([], 0),
        ([True, True], 0),
        ([False, False], 2),
        ([False, True, False, False, True, False], 2),
    ],
)
def test_longest_missing_run_retains_missing_edges(values, expected):
    assert longest_missing_run(pd.Series(values, dtype=bool)) == expected


def audit_fixture(tmp_path, monkeypatch):
    import nyc_mobility.data.weather as module

    source = tmp_path / "data/external/synthetic.parquet"
    source.parent.mkdir(parents=True)
    pd.DataFrame(
        [
            observation(),
            observation(
                "2026-05-01T04:00:00", STATION="WRONG", LATITUDE=np.nan, temperature=np.inf
            ),
        ]
    ).to_parquet(source, index=False)
    source_hash = module.sha256(source)
    (tmp_path / "uv.lock").write_text("synthetic dependency lock")
    spec = tmp_path / "policy.toml"
    spec.write_text(
        f'''[window]
start = "2026-04-30T04:00:00Z"
end = "2026-05-01T04:00:00Z"
[policy]
quality = "source-223-good-only"
delays_hours = [0, 1, 3, 6]
max_age_hours = 6
[[stations]]
id = "SYNTHETIC_NYC"
latitude = 40.78
longitude = -73.97
[[assets]]
file = "data/external/synthetic.parquet"
url = "https://example.invalid/synthetic-test-only.parquet"
sha256 = "{source_hash}"
station_id = "SYNTHETIC_NYC"
'''
    )

    def offline_fetch(url, destination):
        assert destination == source
        return {"url": url, "file": str(destination), "sha256": module.sha256(destination)}

    monkeypatch.setattr(module, "fetch", offline_fetch)
    config = {"split": {"train_start": "2025-12-01", "test_start": "2026-05-01"}}
    return module, source, spec, config


def test_audit_pushes_bounds_into_weather_read_and_preserves_taxi_artifacts(tmp_path, monkeypatch):
    module, source, spec, config = audit_fixture(tmp_path, monkeypatch)
    sentinels = ["data/processed/hourly_demand.parquet", "artifacts/model.joblib"]
    for name in sentinels:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"do not read or alter")
    original_read = pd.read_parquet
    reads = []

    def only_weather(path, **kwargs):
        assert path == source, "Audit attempted to read a non-weather target table"
        assert kwargs["columns"] == module.COLUMNS
        assert kwargs["filters"] == [
            ("DATE", ">=", "2026-04-30T04:00:00"),
            ("DATE", "<", "2026-05-01T04:00:00"),
        ]
        reads.append(path)
        return original_read(path, **kwargs)

    monkeypatch.setattr(pd, "read_parquet", only_weather)
    result = module.audit_weather(config, tmp_path, spec)
    assert reads == [source]
    assert result["core_observation_rows"] == 1
    assert result["expected_hours_per_station"] == 24
    assert result["models_fitted"] == 0 and result["test_metrics"] is None
    assert not result["historical_publication_times_verified"]
    assert not result["eligible_for_point_in_time_model_claim"]
    assert all((tmp_path / name).read_bytes() == b"do not read or alter" for name in sentinels)
    saved = json.loads((tmp_path / "reports/latest_weather.json").read_text())
    assert saved["weather_id"] == result["weather_id"]
    output = tmp_path / "artifacts/weather" / result["weather_id"] / "observations.parquet"
    assert original_read(output).temperature_c.tolist() == [-2.3]


def test_changed_source_hash_aborts_before_read_or_publication(tmp_path, monkeypatch):
    module, _, spec, config = audit_fixture(tmp_path, monkeypatch)
    spec.write_text(spec.read_text().replace('sha256 = "', 'sha256 = "changed-'))

    def forbidden(*args, **kwargs):
        raise AssertionError("Unverified weather reached parsing")

    monkeypatch.setattr(pd, "read_parquet", forbidden)
    with pytest.raises(ValueError, match="Pinned NOAA source changed"):
        module.audit_weather(config, tmp_path, spec)
    assert not (tmp_path / "reports/weather").exists()


def test_sealed_window_violation_fails_before_fetch_or_publication(tmp_path, monkeypatch):
    module, _, spec, config = audit_fixture(tmp_path, monkeypatch)
    spec.write_text(
        spec.read_text().replace('end = "2026-05-01T04:00:00Z"', 'end = "2026-05-02T04:00:00Z"')
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid window reached acquisition")

    monkeypatch.setattr(module, "fetch", forbidden)
    with pytest.raises(ValueError, match="inside the development window"):
        module.audit_weather(config, tmp_path, spec)
    assert not (tmp_path / "reports/weather").exists()
