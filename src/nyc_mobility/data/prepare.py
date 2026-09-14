"""Audit millions of raw records with DuckDB, then build a complete UTC panel."""

from pathlib import Path

import duckdb
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from nyc_mobility.config import TIMEZONE, write_json
from nyc_mobility.data.download import months

REQUIRED = {
    "tpep_pickup_datetime",
    "tpep_dropoff_datetime",
    "PULocationID",
    "DOLocationID",
    "passenger_count",
    "trip_distance",
    "fare_amount",
    "payment_type",
}
BOROUGHS = {"Bronx", "Brooklyn", "Manhattan", "Queens", "Staten Island"}


def validate_schema(path: Path) -> None:
    schema = pq.read_schema(path)
    missing = REQUIRED - set(schema.names)
    if missing:
        raise ValueError(f"{path.name}: missing columns {sorted(missing)}")
    for name in ("tpep_pickup_datetime", "tpep_dropoff_datetime"):
        kind = schema.field(name).type
        if not pa.types.is_timestamp(kind) or kind.tz is not None:
            raise ValueError(f"{name} must contain timezone-naive TLC local timestamps")
    for name in ("PULocationID", "DOLocationID"):
        if not pa.types.is_integer(schema.field(name).type):
            raise ValueError(f"{name} must have an integer type")


def load_zones(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path).rename(columns={"LocationID": "zone_id", "Borough": "borough"})
    if frame.zone_id.duplicated().any():
        raise ValueError("Duplicate Taxi Zone lookup IDs")
    frame = frame.loc[frame.borough.isin(BOROUGHS), ["zone_id", "borough", "Zone"]]
    if frame.empty or not frame.zone_id.between(1, 263).all():
        raise ValueError("Invalid NYC Taxi Zone lookup")
    return frame.sort_values("zone_id").reset_index(drop=True)


def local_hours_to_utc(values: pd.Series) -> pd.Series:
    """Unresolvable fall-back hours and impossible spring hours become NaT."""
    return values.dt.tz_localize(TIMEZONE, ambiguous="NaT", nonexistent="NaT").dt.tz_convert("UTC")


def densify(counts: pd.DataFrame, zones: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    begin = pd.Timestamp(start, tz=TIMEZONE).tz_convert("UTC")
    stop = pd.Timestamp(end, tz=TIMEZONE).tz_convert("UTC")
    hours = pd.date_range(begin, stop, freq="h", inclusive="left")
    # Raw TLC fall-back hours cannot be disambiguated. Refuse to turn missing hours into zeros.
    if hours.tz_convert(TIMEZONE).tz_localize(None).duplicated().any():
        raise ValueError("Fall-back DST range requires an explicit ambiguity strategy")
    index = pd.MultiIndex.from_product([zones.zone_id, hours], names=["zone_id", "hour"])
    values = counts.set_index(["zone_id", "hour"])["demand"]
    if values.index.duplicated().any():
        raise ValueError("Duplicate zone/hour counts")
    panel = values.reindex(index, fill_value=0).rename("demand").reset_index()
    panel["demand"] = panel.demand.astype("int32")
    return panel.merge(zones, on="zone_id", how="left", validate="many_to_one")


def prepare(config: dict, root: Path = Path(".")) -> pd.DataFrame:
    zones = load_zones(root / "data/external/taxi_zone_lookup.csv")
    valid_ids = ",".join(str(int(value)) for value in zones.zone_id)
    counts, audits = [], []
    with duckdb.connect() as connection:
        connection.execute("SET threads=4")
        connection.execute("SET memory_limit='2GB'")
        for month in months(config["data"]["start"], config["data"]["end"]):
            path = root / f"data/raw/yellow_tripdata_{month}.parquet"
            validate_schema(path)
            first = pd.Period(month, "M").start_time
            stop = (pd.Period(month, "M") + 1).start_time
            connection.from_parquet(str(path)).create_view("trips", replace=True)
            # Range and zone checks are independent quality flags; totals may overlap.
            audit = (
                connection.execute(
                    f"""
                SELECT count(*) AS raw_rows,
                  count(*) FILTER (WHERE tpep_pickup_datetime IS NULL) AS null_pickups,
                  count(*) FILTER (WHERE tpep_pickup_datetime < ? OR
                    tpep_pickup_datetime >= ?) AS outside_file_month,
                  count(*) FILTER (WHERE PULocationID IS NULL OR
                    PULocationID NOT IN ({valid_ids})) AS non_nyc_or_invalid_zone,
                  count(*) FILTER (WHERE passenger_count IS NULL) AS missing_passenger_count,
                  count(*) FILTER (WHERE trip_distance <= 0) AS nonpositive_distance,
                  count(*) FILTER (WHERE fare_amount < 0) AS negative_fare,
                  count(*) FILTER (WHERE tpep_dropoff_datetime <= tpep_pickup_datetime)
                    AS nonpositive_duration
                FROM trips
            """,
                    [first, stop],
                )
                .df()
                .iloc[0]
                .astype(int)
                .to_dict()
            )
            monthly = connection.execute(
                f"""
                SELECT CAST(PULocationID AS INTEGER) AS zone_id,
                    date_trunc('hour', tpep_pickup_datetime) AS hour,
                    count(*)::BIGINT AS demand
                FROM trips
                WHERE tpep_pickup_datetime >= ? AND tpep_pickup_datetime < ?
                    AND PULocationID IN ({valid_ids})
                GROUP BY 1, 2
            """,
                [first, stop],
            ).df()
            monthly["hour"] = local_hours_to_utc(monthly.hour)
            audit["unresolvable_dst_pickups"] = int(
                monthly.loc[monthly.hour.isna(), "demand"].sum()
            )
            monthly = monthly.dropna(subset=["hour"])
            audit["accepted_pickups"] = int(monthly.demand.sum())
            audit["excluded_pickups"] = audit["raw_rows"] - audit["accepted_pickups"]
            audit["month"] = month
            audits.append(audit)
            counts.append(monthly)
            print(f"Aggregated {month}: {audit['accepted_pickups']:,} pickups", flush=True)
    end = (pd.Period(config["data"]["end"], "M") + 1).start_time.isoformat()
    start = pd.Period(config["data"]["start"], "M").start_time.isoformat()
    panel = densify(pd.concat(counts, ignore_index=True), zones, start, end)
    output = root / "data/processed/hourly_demand.parquet"
    output.parent.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(output, index=False)
    write_json(
        root / "reports/data_quality.json",
        {
            "months": audits,
            "panel_rows": len(panel),
            "nyc_zones": len(zones),
            "utc_hours": panel.hour.nunique(),
            "total_pickups": int(panel.demand.sum()),
            "zero_demand_fraction": float(panel.demand.eq(0).mean()),
            "scope": "Yellow taxi recorded pickups in NYC; not unmet demand or all mobility",
            "zero_policy": "Unobserved zone-hours in available monthly files assumed zero",
            "dst_policy": "Reject ambiguous fall-back ranges; exclude impossible spring timestamps",
        },
    )
    return panel
