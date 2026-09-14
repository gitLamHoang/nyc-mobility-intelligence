"""Development-only duplicate sensitivity and historical reporting-volume checks.

This audit never changes canonical labels, promotes a model, or evaluates held-out targets.
"""

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import duckdb
import numpy as np
import pandas as pd

from nyc_mobility.config import TIMEZONE, write_json
from nyc_mobility.data.download import months, sha256
from nyc_mobility.data.prepare import (
    densify,
    load_zones,
    local_hours_to_utc,
    validate_schema,
)
from nyc_mobility.evaluation.metrics import metrics
from nyc_mobility.evaluation.splits import chronological_split, local_boundary
from nyc_mobility.features.temporal import FEATURES, make_features
from nyc_mobility.models.baselines import baseline_predictions


def development_range(config: dict) -> tuple[list[str], pd.Timestamp, pd.Timestamp]:
    """Derive source months from train/test boundaries, never from data.end alone."""
    start = pd.Timestamp(config["split"]["train_start"])
    stop = pd.Timestamp(config["split"]["test_start"])
    validation = pd.Timestamp(config["split"]["validation_start"])
    if not start < validation < stop:
        raise ValueError("Development partitions must be increasing")
    if (
        start < pd.Period(config["data"]["start"], "M").start_time
        or stop > (pd.Period(config["data"]["end"], "M") + 1).start_time
    ):
        raise ValueError("Development range is not covered by configured data months")
    last_month = (stop - pd.Timedelta(nanoseconds=1)).strftime("%Y-%m")
    return months(start.strftime("%Y-%m"), last_month), start, stop


def audit_month(
    connection: duckdb.DuckDBPyConnection,
    path: Path,
    start: pd.Timestamp,
    stop: pd.Timestamp,
    zone_ids: list[int],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Use all original columns to identify exact repeated rows, including equal NULLs."""
    validate_schema(path)
    relation = connection.from_parquet(str(path))
    if "VendorID" not in relation.columns:
        raise ValueError("VendorID is required for the reporting-volume audit")
    relation.create_view("audit_trips", replace=True)
    ids = ",".join(str(int(value)) for value in zone_ids)
    eligible = f"tpep_pickup_datetime >= ? AND tpep_pickup_datetime < ? AND PULocationID IN ({ids})"
    parameters = [start, stop]
    counts = connection.execute(
        f"""SELECT PULocationID AS zone_id, date_trunc('hour', tpep_pickup_datetime) AS hour,
            count(*)::BIGINT AS demand FROM audit_trips WHERE {eligible} GROUP BY 1, 2""",
        parameters,
    ).df()
    # HAVING stores only repeated groups. No lossy row hash or partial trip key is used.
    connection.execute(
        f"""CREATE OR REPLACE TEMP TABLE repeated_rows AS
            SELECT *, count(*)::BIGINT AS copies FROM audit_trips
            WHERE {eligible} GROUP BY ALL HAVING count(*) > 1""",
        parameters,
    )
    duplicates = connection.execute(
        """SELECT PULocationID AS zone_id, date_trunc('hour', tpep_pickup_datetime) AS hour,
            sum(copies - 1)::BIGINT AS duplicate_excess,
            count(*)::BIGINT AS duplicate_groups,
            sum(copies)::BIGINT AS repeated_rows, max(copies)::BIGINT AS max_copies
            FROM repeated_rows GROUP BY 1, 2"""
    ).df()
    vendors = connection.execute(
        f"""SELECT coalesce(CAST(VendorID AS VARCHAR), 'missing') AS vendor,
            date_trunc('hour', tpep_pickup_datetime) AS hour, count(*)::BIGINT AS demand
            FROM audit_trips WHERE {eligible} GROUP BY 1, 2""",
        parameters,
    ).df()
    for frame in (counts, duplicates, vendors):
        frame["hour"] = local_hours_to_utc(frame.hour)
        frame.dropna(subset=["hour"], inplace=True)
    return counts, duplicates, vendors


def reporting_volume_flags(
    volumes: pd.DataFrame, min_reference: float = 100, fraction: float = 0.1
) -> pd.DataFrame:
    """Compare each series with the median of the preceding four elapsed weekly hours.

    At least three historical matches and reference >=100 are required by default.
    These are retrospective investigation flags, not confirmed outages or model features.
    """
    if min_reference <= 0 or not 0 < fraction < 1:
        raise ValueError("Invalid coverage thresholds")
    ordered = volumes.sort_values(["series", "hour"]).reset_index(drop=True).copy()
    if ordered.empty or ordered.series.isna().any() or ordered.duplicated(["series", "hour"]).any():
        raise ValueError("Reporting series must be nonempty and unique per hour")
    if not isinstance(ordered.hour.dtype, pd.DatetimeTZDtype) or ordered.hour.isna().any():
        raise ValueError("Reporting hours must be timezone-aware and nonmissing")
    values = ordered.demand.to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values < 0).any() or (values % 1 != 0).any():
        raise ValueError("Reporting counts must be finite nonnegative integers")
    if not ordered.hour.eq(ordered.hour.dt.floor("h")).all():
        raise ValueError("Reporting timestamps must be hour boundaries")
    if not ordered.groupby("series").hour.diff().dropna().eq(pd.Timedelta(hours=1)).all():
        raise ValueError("Reporting series must have a contiguous hourly grid")
    grouped = ordered.groupby("series").demand
    prior = pd.concat([grouped.shift(168 * week) for week in range(1, 5)], axis=1)
    ordered["reference_matches"] = prior.notna().sum(axis=1)
    ordered["historical_median"] = prior.median(axis=1)
    ordered["coverage_ratio"] = ordered.demand / ordered.historical_median.where(
        ordered.historical_median.gt(0)
    )
    ordered["flag"] = (
        ordered.reference_matches.ge(3)
        & ordered.historical_median.ge(min_reference)
        & ordered.coverage_ratio.lt(fraction)
    )
    return ordered


def baseline_sensitivity(panel: pd.DataFrame, split: dict) -> dict:
    """Recompute every historical feature and average under the alternate count policy."""
    featured = make_features(panel).dropna(subset=FEATURES)
    train, valid = chronological_split(featured, split)
    return {
        name: metrics(valid.demand, values)
        for name, values in baseline_predictions(train, valid).items()
    }


def quality_audit(config: dict, root: Path = Path(".")) -> dict:
    source_months, start, stop = development_range(config)
    zones = load_zones(root / "data/external/taxi_zone_lookup.csv")
    zone_ids = zones.zone_id.tolist()
    manifest = json.loads((root / "reports/data_manifest.json").read_text())
    recorded_hashes = {Path(item["file"]).name: item["sha256"] for item in manifest}
    source_hashes = {}
    # Preflight all required sources before writing audit reports or starting expensive work.
    paths = [root / f"data/raw/yellow_tripdata_{month}.parquet" for month in source_months]
    for path in [*paths, root / "data/external/taxi_zone_lookup.csv"]:
        digest = sha256(path)
        if recorded_hashes.get(path.name) != digest:
            raise ValueError(f"Source does not match acquisition manifest: {path.name}")
        source_hashes[path.name] = digest
    count_frames, duplicate_frames, vendor_frames, monthly = [], [], [], []
    with duckdb.connect() as connection:
        connection.execute("SET threads=4")
        connection.execute("SET memory_limit='2GB'")
        temporary = root / "work/duckdb-quality-audit"
        temporary.mkdir(parents=True, exist_ok=True)
        connection.execute("SET temp_directory = ?", [str(temporary)])
        for month, path in zip(source_months, paths, strict=True):
            first = max(start, pd.Period(month, "M").start_time)
            last = min(stop, (pd.Period(month, "M") + 1).start_time)
            counts, duplicates, vendors = audit_month(connection, path, first, last, zone_ids)
            count_frames.append(counts)
            duplicate_frames.append(duplicates)
            vendor_frames.append(vendors)
            summary = {
                "month": month,
                "eligible_pickups": int(counts.demand.sum()),
                "exact_duplicate_excess": int(duplicates.duplicate_excess.sum()),
                "exact_duplicate_groups": int(duplicates.duplicate_groups.sum()),
                "repeated_rows": int(duplicates.repeated_rows.sum()),
                "max_copies": int(duplicates.max_copies.max()) if len(duplicates) else 1,
                "affected_zone_hours": len(duplicates),
            }
            monthly.append(summary)
            print(
                f"Audited {month}: {summary['exact_duplicate_excess']:,} exact excess rows "
                f"/ {summary['eligible_pickups']:,} eligible pickups",
                flush=True,
            )
    panel = densify(pd.concat(count_frames, ignore_index=True), zones, str(start), str(stop))
    if panel.demand.sum() == 0:
        raise ValueError("No eligible pickups in the development range")
    duplicates = pd.concat(duplicate_frames, ignore_index=True)
    canonical_path = root / "data/processed/hourly_demand.parquet"
    canonical = pd.read_parquet(
        canonical_path,
        filters=[
            ("hour", ">=", local_boundary(str(start))),
            ("hour", "<", local_boundary(str(stop))),
        ],
    )
    keys = ["zone_id", "hour", "demand"]
    pd.testing.assert_frame_equal(
        panel[keys].reset_index(drop=True),
        canonical.sort_values(["zone_id", "hour"])[keys].reset_index(drop=True),
        check_dtype=False,
    )
    alternative = panel.merge(
        duplicates[["zone_id", "hour", "duplicate_excess"]],
        on=["zone_id", "hour"],
        how="left",
        validate="one_to_one",
    )
    alternative["duplicate_excess"] = alternative.duplicate_excess.fillna(0).astype("int32")
    alternative["demand"] = alternative.demand - alternative.duplicate_excess
    hours = pd.DatetimeIndex(sorted(panel.hour.unique()))
    city = panel.groupby("hour").demand.sum().reindex(hours)
    vendor_counts = pd.concat(vendor_frames, ignore_index=True)
    if int(vendor_counts.demand.sum()) != int(city.sum()):
        raise ValueError("Vendor counts do not conserve city pickup totals")
    grid = pd.MultiIndex.from_product(
        [sorted(vendor_counts.vendor.unique()), hours], names=["vendor", "hour"]
    )
    vendor_grid = vendor_counts.set_index(["vendor", "hour"]).demand.reindex(grid, fill_value=0)
    volumes = vendor_grid.reset_index().rename(columns={"vendor": "series"})
    volumes["series"] = "vendor_" + volumes.series
    city_frame = pd.DataFrame({"series": "city", "hour": hours, "demand": city.to_numpy()})
    coverage = reporting_volume_flags(pd.concat([city_frame, volumes], ignore_index=True))
    flagged = coverage.loc[coverage.flag].copy()
    flagged["hour_nyc"] = flagged.hour.dt.tz_convert(TIMEZONE)
    sensitivity = {
        "recorded_counts": baseline_sensitivity(panel, config["split"]),
        "exact_dedup_scenario": baseline_sensitivity(alternative, config["split"]),
    }
    identifier = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:6]
    output = root / "reports/quality_audits" / identifier
    output.mkdir(parents=True, exist_ok=False)
    local = root / "artifacts/quality_audits" / identifier
    local.mkdir(parents=True, exist_ok=False)
    coverage.to_parquet(local / "reporting_volumes.parquet", index=False)
    alternative.to_parquet(local / "exact_dedup_scenario.parquet", index=False)
    flagged.to_csv(output / "reporting_volume_flags.csv", index=False)
    pd.DataFrame(monthly).to_csv(output / "duplicates_by_month.csv", index=False)
    zone_effect = alternative.groupby(["zone_id", "Zone", "borough"]).agg(
        exact_duplicate_excess=("duplicate_excess", "sum"),
        affected_zone_hours=("duplicate_excess", lambda values: int(values.gt(0).sum())),
    )
    zone_effect.to_csv(output / "duplicates_by_zone.csv")
    excess = int(alternative.duplicate_excess.sum())
    record = {
        "audit_id": identifier,
        "created_at": datetime.now(UTC).isoformat(),
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
        "source_hashes": source_hashes,
        "canonical_panel_sha256": sha256(canonical_path),
        "code_hashes": {
            str(path.relative_to(root)): sha256(path)
            for path in sorted((root / "src").rglob("*.py"))
        },
        "lockfile_sha256": sha256(root / "uv.lock"),
        "config": config,
        "development_start_local": str(start),
        "development_end_local_exclusive": str(stop),
        "source_months": source_months,
        "months": monthly,
        "eligible_pickups": int(panel.demand.sum()),
        "utc_hours": len(hours),
        "nyc_zones": len(zones),
        "exact_duplicate_excess": excess,
        "exact_duplicate_excess_pct": 100 * excess / int(panel.demand.sum()),
        "affected_zone_hours": int(alternative.duplicate_excess.gt(0).sum()),
        "max_zone_hour_reduction": int(alternative.duplicate_excess.max()),
        "city_zero_hours": int(city.eq(0).sum()),
        "vendor_zero_hours": volumes.groupby("series")
        .demand.apply(lambda values: int(values.eq(0).sum()))
        .to_dict(),
        "vendor_pickups": volumes.groupby("series").demand.sum().to_dict(),
        "volume_flags_by_series": flagged.groupby("series").size().to_dict(),
        "coverage_rule": {
            "prior_week_offsets_hours": [168, 336, 504, 672],
            "minimum_matches": 3,
            "minimum_median": 100,
            "flag_ratio_below": 0.1,
        },
        "baseline_metrics": sensitivity,
        "test_metrics": None,
        "canonical_labels_changed": False,
        "interpretation": "All-column SQL-equal rows are suspicious, not proven duplicate trips. "
        "Dedup scores use changed labels and features, not a model improvement. "
        "Low reporting volume is not proof of an outage. No automatic removal.",
    }
    write_json(output / "audit.json", record)
    write_json(root / "reports/latest_quality_audit.json", record)
    print(f"Quality audit saved: {output}", flush=True)
    return record
