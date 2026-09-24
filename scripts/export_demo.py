"""Export a compact historical April demo from hash-verified study predictions."""

import json
from pathlib import Path
from zipfile import ZipFile

import duckdb
import geopandas as gpd
import numpy as np
import pandas as pd

from nyc_mobility.config import write_json
from nyc_mobility.data.download import sha256

SOURCE = Path("reports/borough/20260924T162406Z-c35816/metrics.json")
OUTPUT = Path("web/public/data/demo.json")


def export_demo():
    record = json.loads(SOURCE.read_text())
    predictions = Path("artifacts/borough") / record["borough_id"] / "fold_3.parquet"
    if sha256(predictions) != record["prediction_sha256"]["fold_3"]:
        raise ValueError("Demo predictions differ from the audited study")
    start, stop = pd.Timestamp("2026-04-07T04:00Z"), pd.Timestamp("2026-04-09T04:00Z")
    frame = pd.read_parquet(predictions, filters=[("hour", ">=", start), ("hour", "<", stop)])
    if len(frame) != 48 * 262 or frame.duplicated(["zone_id", "hour"]).any():
        raise ValueError("Demo requires exactly 48 complete April hours across 262 zones")
    archive = Path("data/external/taxi_zones.zip").resolve()
    audit = json.loads(Path("reports/latest_spatial_preparation.json").read_text())
    if sha256(archive) != audit["input_sha256"]["data/external/taxi_zones.zip"]:
        raise ValueError("Unexpected display geometry")
    with ZipFile(archive) as z:
        (member,) = [name for name in z.namelist() if name.endswith(".shp")]
    geo = gpd.read_file(f"zip://{archive}!{member}")
    geo = geo.loc[geo.LocationID.isin(frame.zone_id.unique())].sort_values("LocationID")
    xmin, ymin, xmax, ymax = geo.total_bounds
    scale = 900 / max(xmax - xmin, ymax - ymin)

    def path_string(shape):
        polygons = list(shape.geoms) if shape.geom_type == "MultiPolygon" else [shape]
        paths = []
        for polygon in polygons:
            for ring in [polygon.exterior, *polygon.interiors]:
                points = [
                    (20 + (x - xmin) * scale, 20 + (ymax - y) * scale) for x, y in ring.coords
                ]
                paths.append("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in points) + "Z")
        return "".join(paths)

    zones = [
        {
            "id": int(r.LocationID),
            "name": r.zone,
            "borough": r.borough,
            "path": path_string(r.geometry.simplify(80, preserve_topology=True)),
        }
        for r in geo.itertuples()
    ]
    ids = [r["id"] for r in zones]
    names = ["demand", "hist_gradient_boosting", "borough_context", "previous_week_168h"]
    hours = []
    for hour, rows in frame.groupby("hour", sort=True):
        values = rows.set_index("zone_id").loc[ids, names].to_numpy()
        if not np.isfinite(values).all() or (values < 0).any():
            raise ValueError("Invalid observed or predicted values")
        hours.append({"time": hour.isoformat(), "values": values.round(6).tolist()})
    with duckdb.connect() as conn:
        conn.register("demo", frame)
        summary = conn.sql(Path("sql/demo_summary.sql").read_text()).df().to_dict("records")
    result = {
        "schemaVersion": 1,
        "studyId": record["borough_id"],
        "scope": "April 7–8, 2026 · historical validation · America/New_York",
        "columns": names,
        "zones": zones,
        "hours": hours,
        "boroughSummary": summary,
        "viewBox": [
            0,
            0,
            round(40 + (xmax - xmin) * scale, 1),
            round(40 + (ymax - ymin) * scale, 1),
        ],
        "provenance": {
            "studySha256": sha256(SOURCE),
            "predictionsSha256": sha256(predictions),
            "geometrySha256": sha256(archive),
            "sqlSha256": sha256(Path("sql/demo_summary.sql")),
        },
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, separators=(",", ":"), allow_nan=False) + "\n")
    write_json(
        Path("reports/demo_export.json"),
        {
            "study_id": record["borough_id"],
            "hours": len(hours),
            "zones": len(zones),
            "rows": len(frame),
            "start_utc": start.isoformat(),
            "stop_exclusive_utc": stop.isoformat(),
            "output_sha256": sha256(OUTPUT),
            "output_bytes": OUTPUT.stat().st_size,
            "provenance": result["provenance"],
            "models_fitted": 0,
            "test_metrics": None,
        },
    )
    print(f"Exported {len(frame):,} historical zone-hours ({OUTPUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    export_demo()
