"""Audit pinned NOAA GHCNh development observations without fitting or reading taxi targets."""

import subprocess
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd

from nyc_mobility.config import TIMEZONE, write_json
from nyc_mobility.data.download import fetch, sha256
from nyc_mobility.features.weather import WEATHER_VALUES, weather_snapshots

FIELDS = {
    "temperature": "temperature_c",
    "dew_point_temperature": "dew_point_c",
    "wind_speed": "wind_speed_m_s",
}
AUDIT_FIELDS = [*FIELDS, "precipitation"]
SUFFIXES = ["", "_Source_Code", "_Quality_Code", "_Measurement_Code", "_Report_Type"]
COLUMNS = ["STATION", "DATE", "LATITUDE", "LONGITUDE"] + [
    field + suffix for field in AUDIT_FIELDS for suffix in SUFFIXES
]


def parse_observations(
    raw: pd.DataFrame, station: dict, start: pd.Timestamp, end: pd.Timestamp
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Conservatively retain documented source-223 good values; audit every other flag.

    Raw GHCNh DATE is a UTC ISO string without a suffix. Values are already in SI units.
    Bounds are half-open UTC instants. No weather after the development end is parsed.
    """
    for bound in (start, end):
        if pd.isna(bound) or str(bound.tzinfo) != "UTC":
            raise ValueError("Weather boundaries must be explicit UTC instants")
    if start >= end:
        raise ValueError("Weather window must be increasing")
    if not set(COLUMNS).issubset(raw.columns):
        raise ValueError("Missing required GHCNh columns")
    # Station-year sources have fixed-width ISO UTC dates; fail malformed structure.
    if not raw.DATE.str.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", na=False).all():
        raise ValueError("GHCNh dates must have documented UTC ISO form")
    frame = raw.loc[
        raw.DATE.ge(start.strftime("%Y-%m-%dT%H:%M:%S"))
        & raw.DATE.lt(end.strftime("%Y-%m-%dT%H:%M:%S"))
    ].copy()
    if frame.empty:
        raise ValueError("No development weather observations")
    if not frame.STATION.eq(station["id"]).all():
        raise ValueError("Weather station identity mismatch")
    for field, key in (("LATITUDE", "latitude"), ("LONGITUDE", "longitude")):
        coordinates = pd.to_numeric(frame[field], errors="raise")
        if (
            not np.isfinite(coordinates).all()
            or not np.isclose(coordinates, station[key], atol=0.01, rtol=0).all()
        ):
            raise ValueError("Weather station coordinates mismatch")
    observed = pd.to_datetime(frame.DATE, format="%Y-%m-%dT%H:%M:%S", utc=True)
    if observed.duplicated().any():
        raise ValueError("Duplicate station observation time")
    clean = pd.DataFrame({"station_id": station["id"], "observed_at": observed})
    audit = []
    core_present = pd.Series(False, index=frame.index)
    month = observed.dt.tz_convert(TIMEZONE).dt.strftime("%Y-%m")
    for field in AUDIT_FIELDS:
        values = pd.to_numeric(frame[field], errors="raise")
        if np.isinf(values).any():
            raise ValueError("Infinite weather measurements")
        present = values.notna()
        source = frame[field + "_Source_Code"].fillna("").astype(str)
        quality = frame[field + "_Quality_Code"].fillna("").astype(str)
        measure = frame[field + "_Measurement_Code"].fillna("").astype(str)
        report = frame[field + "_Report_Type"].fillna("").astype(str)
        accepted = present & source.eq("223") & quality.eq("1")
        accepted &= report.isin(["FM12", "FM15", "FM16"])
        if field == "wind_speed":
            accepted &= measure.isin(["C", "N", "V"]) & values.ge(0)
        else:
            accepted &= measure.eq("")
        if field in FIELDS:
            core_present |= present
            clean[FIELDS[field]] = values.where(accepted)
        else:
            # Precipitation is audited only: traces/accumulations need a separate policy.
            accepted[:] = False
        summary = pd.DataFrame(
            {
                "month": month,
                "source": source,
                "quality": quality,
                "measurement": measure,
                "report_type": report,
                "present": present,
                "accepted": accepted,
            }
        )
        for keys, group in summary.groupby(
            ["month", "source", "quality", "measurement", "report_type"], dropna=False
        ):
            audit.append(
                dict(
                    zip(
                        ["month", "source", "quality", "measurement", "report_type"],
                        keys,
                        strict=True,
                    ),
                    station_id=station["id"],
                    variable=field,
                    rows=len(group),
                    present=int(group.present.sum()),
                    accepted=int(group.accepted.sum()),
                    policy_excluded=int((group.present & ~group.accepted).sum()),
                )
            )
    # Omit unrelated precipitation-only rows, but retain rejected/missing core fields
    # in a real core observation: never substitute an older good reading silently.
    return clean.loc[core_present].sort_values("observed_at").reset_index(drop=True), pd.DataFrame(
        audit
    )


def longest_missing_run(present: pd.Series) -> int:
    missing = ~present.astype(bool)
    return int(missing.groupby(present.astype(bool).cumsum()).sum().max()) if len(missing) else 0


def audit_weather(
    config: dict, root: Path = Path("."), spec_path: Path = Path("configs/weather_inputs.toml")
) -> dict:
    root = root.resolve()
    path = spec_path if spec_path.is_absolute() else root / spec_path
    spec_hash = sha256(path)
    spec = tomllib.loads(path.read_text())
    start = pd.Timestamp(spec["window"]["start"]).tz_convert("UTC")
    end = pd.Timestamp(spec["window"]["end"]).tz_convert("UTC")
    sealed = pd.Timestamp(config["split"]["test_start"], tz=TIMEZONE).tz_convert("UTC")
    train_start = pd.Timestamp(config["split"]["train_start"], tz=TIMEZONE).tz_convert("UTC")
    if start < train_start or end > sealed or start >= end:
        raise ValueError("Weather audit must remain inside the development window")
    policy = spec["policy"]
    if policy["quality"] != "source-223-good-only" or policy["delays_hours"] != [0, 1, 3, 6]:
        raise ValueError("Unsupported weather audit policy")
    source_paths = sorted((root / "src").rglob("*.py"))
    before = {str(p.relative_to(root)): sha256(p) for p in source_paths}
    before[str(path.relative_to(root))] = spec_hash
    before["uv.lock"] = sha256(root / "uv.lock")
    stations = {s["id"]: s for s in spec["stations"]}
    if len(stations) != len(spec["stations"]):
        raise ValueError("Duplicate configured station")
    sources, raw_parts = [], {key: [] for key in stations}
    for asset in spec["assets"]:
        destination = root / asset["file"]
        info = fetch(asset["url"], destination)
        if info["sha256"] != asset["sha256"] or sha256(destination) != asset["sha256"]:
            raise ValueError(f"Pinned NOAA source changed: {destination.name}")
        before[asset["file"]] = asset["sha256"]
        sources.append({**info, "file": asset["file"]})
        if asset.get("station_id"):
            # Push down bounds: annual archives include later weather, never May taxi labels.
            raw_parts[asset["station_id"]].append(
                pd.read_parquet(
                    destination,
                    columns=COLUMNS,
                    filters=[
                        ("DATE", ">=", start.strftime("%Y-%m-%dT%H:%M:%S")),
                        ("DATE", "<", end.strftime("%Y-%m-%dT%H:%M:%S")),
                    ],
                )
            )
    observations, flags, native = [], [], []
    targets = pd.date_range(start, end, freq="h", inclusive="left")
    for station_id, parts in raw_parts.items():
        if not parts:
            raise ValueError("Configured weather station has no assets")
        raw = pd.concat(parts, ignore_index=True)
        clean, audit = parse_observations(raw, stations[station_id], start, end)
        observations.append(clean)
        flags.append(audit)
        hours = clean.observed_at.dt.floor("h")
        for variable in WEATHER_VALUES:
            present = clean.loc[clean[variable].notna(), "observed_at"].dt.floor("h")
            covered = pd.Series(targets.isin(present), index=targets)
            native.append(
                {
                    "station_id": station_id,
                    "variable": variable,
                    "source_rows": len(raw),
                    "core_observation_rows": len(clean),
                    "core_observed_hours": hours.nunique(),
                    "accepted_values": int(clean[variable].notna().sum()),
                    "accepted_hours": int(covered.sum()),
                    "expected_hours": len(targets),
                    "longest_missing_hours": longest_missing_run(covered),
                    "min": clean[variable].min(),
                    "max": clean[variable].max(),
                }
            )
    observations = pd.concat(observations, ignore_index=True)
    snapshots, coverage = [], []
    for delay in policy["delays_hours"]:
        current = weather_snapshots(observations, targets, delay, policy["max_age_hours"])
        current["delay_hours"] = delay
        snapshots.append(current)
        current["month"] = current.hour.dt.tz_convert(TIMEZONE).dt.strftime("%Y-%m")
        for (station_id, month), group in current.groupby(["station_id", "month"]):
            complete = group[WEATHER_VALUES].notna().all(axis=1)
            coverage.append(
                {
                    "station_id": station_id,
                    "month": month,
                    "delay_hours": delay,
                    "target_hours": len(group),
                    "matched_observation_hours": int(group.observed_at.notna().sum()),
                    "complete_hours": int(complete.sum()),
                    "complete_fraction": float(complete.mean()),
                    **{f"{v}_hours": int(group[v].notna().sum()) for v in WEATHER_VALUES},
                }
            )
    for relative, expected in before.items():
        if sha256(root / relative) != expected:
            raise ValueError(f"Weather input/source changed during audit: {relative}")
    audit_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:6]
    output = root / "reports/weather" / audit_id
    artifact = root / "artifacts/weather" / audit_id
    output.mkdir(parents=True)
    artifact.mkdir(parents=True)
    observations.to_parquet(artifact / "observations.parquet", index=False)
    pd.concat(snapshots, ignore_index=True).to_parquet(artifact / "snapshots.parquet", index=False)
    pd.concat(flags, ignore_index=True).to_csv(output / "quality_flags.csv", index=False)
    pd.DataFrame(native).to_csv(output / "native_coverage.csv", index=False)
    pd.DataFrame(coverage).to_csv(output / "availability_coverage.csv", index=False)
    result = {
        "weather_id": audit_id,
        "created_at": datetime.now(UTC).isoformat(),
        "window_start_utc": start,
        "window_end_utc_exclusive": end,
        "expected_hours_per_station": len(targets),
        "stations": spec["stations"],
        "core_observation_rows": len(observations),
        "policy": policy,
        "sources": sources,
        "input_source_lock_hashes": before,
        "config": config,
        "outputs_sha256": {
            str(p.relative_to(root)): sha256(p)
            for p in sorted([*output.glob("*.csv"), *artifact.glob("*.parquet")])
        },
        "versions": {"pandas": pd.__version__, "numpy": np.__version__},
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
        "historical_publication_times_verified": False,
        "eligible_for_point_in_time_model_claim": False,
        "weather_model_protocol_frozen": False,
        "models_fitted": 0,
        "serving_model_changed": False,
        "test_metrics": None,
    }
    write_json(output / "metrics.json", result)
    write_json(root / "reports/latest_weather.json", result)
    print(f"Weather audit: {audit_id}; {len(observations):,} core observations; no model fits")
    return result
