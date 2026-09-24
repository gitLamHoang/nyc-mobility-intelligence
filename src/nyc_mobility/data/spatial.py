"""Audit official geometry versions and prepare eligible borough features, without fitting."""

import hashlib
import json
import subprocess
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

from nyc_mobility.config import TIMEZONE, write_json
from nyc_mobility.data.download import fetch, sha256
from nyc_mobility.data.prepare import load_zones
from nyc_mobility.evaluation.backtest import read_development_panel
from nyc_mobility.evaluation.splits import local_boundary, require_complete_window
from nyc_mobility.features.borough import CONTEXT_FEATURES, STATIC_FEATURES, make_borough_features
from nyc_mobility.features.temporal import FEATURES, make_features


def geometry_identity(frame: gpd.GeoDataFrame, zones: pd.DataFrame) -> dict:
    """Report duplicate/missing IDs without inferring correspondence from row order."""
    if frame.zone_id.isna().any() or (frame.zone_id % 1 != 0).any():
        raise ValueError("Geometry IDs must be nonmissing integers")
    counts = frame.zone_id.value_counts()
    expected, found = set(zones.zone_id), set(frame.zone_id)
    return {
        "rows": len(frame),
        "unique_zone_ids": len(found),
        "duplicate_zone_ids": {str(k): int(v) for k, v in counts.items() if v > 1},
        "missing_nyc_zone_ids": sorted(expected - found),
        "outside_nyc_zone_ids": sorted(found - expected),
        "invalid_geometries": int((~frame.is_valid).sum()),
        "empty_geometries": int(frame.is_empty.sum()),
        "missing_geometries": int(frame.geometry.isna().sum()),
        "one_to_one_nyc_mapping": not counts.gt(1).any() and expected <= found,
    }


def boundary_graph(frame: gpd.GeoDataFrame, zones: pd.DataFrame, policy: dict):
    identity = geometry_identity(frame, zones)
    if not identity["one_to_one_nyc_mapping"]:
        raise ValueError("Geometry cannot be joined one-to-one to all NYC zone IDs")
    if any(
        identity[key] for key in ["invalid_geometries", "empty_geometries", "missing_geometries"]
    ):
        raise ValueError("Geometry must be valid, nonempty polygons")
    if frame.crs is None or frame.crs.to_epsg() != 2263:
        raise ValueError("Boundary audit requires EPSG:2263 projected coordinates")
    if not frame.geom_type.isin(["Polygon", "MultiPolygon"]).all():
        raise ValueError("Boundary audit requires polygonal geometry")
    minimum, maximum = policy["shared_boundary_min_m"], policy["maximum_pair_overlap_m2"]
    if not np.isfinite([minimum, maximum]).all() or minimum <= 0 or maximum < 0:
        raise ValueError("Boundary threshold must be positive and overlap tolerance nonnegative")
    geo = frame.loc[frame.zone_id.isin(zones.zone_id)].sort_values("zone_id").reset_index(drop=True)
    check = geo[["zone_id", "borough"]].merge(zones, on="zone_id", validate="one_to_one")
    if not check.borough_x.eq(check.borough_y).all():
        raise ValueError("Geometry boroughs disagree with the lookup")
    unit = geo.crs.axis_info[0].unit_conversion_factor
    pairs = []
    for i, row in geo.iterrows():
        for j in geo.sindex.query(row.geometry, predicate="intersects"):
            if j <= i:
                continue
            other = geo.iloc[j]
            overlap = row.geometry.intersection(other.geometry).area * unit**2
            if overlap > maximum:
                raise ValueError("Polygon overlap exceeds the audit tolerance")
            boundary = row.geometry.boundary.intersection(other.geometry.boundary).length * unit
            pairs.append(
                {
                    "zone_id": int(row.zone_id),
                    "neighbor_id": int(other.zone_id),
                    "shared_boundary_m": boundary,
                    "overlap_m2": overlap,
                    "qualifies": boundary >= minimum,
                }
            )
    pairs = pd.DataFrame(
        pairs, columns=["zone_id", "neighbor_id", "shared_boundary_m", "overlap_m2", "qualifies"]
    )
    edges = pairs.loc[pairs.qualifies.astype(bool)].sort_values(["zone_id", "neighbor_id"])
    degrees = pd.concat([edges.zone_id, edges.neighbor_id]).value_counts()
    nodes = geo[["zone_id"]].merge(zones, on="zone_id", validate="one_to_one")
    nodes["area_km2"] = geo.area.to_numpy() * unit**2 / 1e6
    nodes["neighbor_count"] = nodes.zone_id.map(degrees).fillna(0).astype(int)
    return nodes, edges, pairs


def prepare_spatial(
    config: dict, root: Path = Path("."), spec_path: Path = Path("configs/spatial_inputs.toml")
) -> dict:
    root = root.resolve()
    path = spec_path if spec_path.is_absolute() else root / spec_path
    spec = tomllib.loads(path.read_text())
    input_hashes = {str(path.relative_to(root)): sha256(path)}
    for asset in spec["assets"]:
        p = root / asset["file"]
        if not p.exists():
            fetch(asset["url"], p)
        if sha256(p) != asset["sha256"]:
            raise ValueError(f"Pinned spatial source hash mismatch: {p.name}")
        input_hashes[asset["file"]] = asset["sha256"]
    zones = load_zones(root / "data/external/taxi_zone_lookup.csv")
    archive = (root / "data/external/taxi_zones.zip").resolve()
    with ZipFile(archive) as contents:
        members = [n for n in contents.namelist() if n.endswith(".shp")]
        timestamps = {i.filename: list(i.date_time) for i in contents.infolist() if not i.is_dir()}
    if len(members) != 1:
        raise ValueError("Expected one official shapefile")
    current = gpd.read_file(f"zip://{archive}!{members[0]}").rename(
        columns={"LocationID": "zone_id"}
    )
    older = gpd.read_file(root / "data/external/taxi_zones_opendata.geojson")
    older["zone_id"] = pd.to_numeric(older.locationid, errors="raise")
    metadata = json.loads((root / "data/external/taxi_zones_opendata_metadata.json").read_text())
    nodes, edges, pairs = boundary_graph(current, zones, spec["policy"])
    data = root / "data/processed/hourly_demand.parquet"
    input_hashes[str(data.relative_to(root))] = sha256(data)
    origin = local_boundary(config["split"]["train_start"])
    cutoff = local_boundary(config["split"]["test_start"])
    panel = read_development_panel(data, origin, cutoff)
    require_complete_window(panel, zones.zone_id.tolist(), origin, cutoff)
    features = make_borough_features(
        panel, zones, lookup_available_at=spec["policy"]["lookup_available_at"]
    )
    temporal = make_features(panel)
    pd.testing.assert_frame_equal(features[list(temporal)], temporal)
    usable = features.dropna(subset=[*FEATURES, *STATIC_FEATURES, *CONTEXT_FEATURES])
    identifier = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:6]
    output = root / "reports/spatial_preparation" / identifier
    artifacts = root / "artifacts/spatial_preparation" / identifier
    output.mkdir(parents=True, exist_ok=False)
    artifacts.mkdir(parents=True, exist_ok=False)
    nodes.to_csv(output / "zone_geometry.csv", index=False)
    pairs.to_csv(output / "boundary_pairs.csv", index=False)
    features.to_parquet(artifacts / "borough_features.parquet", index=False)
    usable[STATIC_FEATURES + CONTEXT_FEATURES].describe().to_csv(output / "feature_summary.csv")
    for name, expected in input_hashes.items():
        if sha256(root / name) != expected:
            raise ValueError("Spatial input changed during preparation")
    result = {
        "spatial_preparation_id": identifier,
        "created_at": datetime.now(UTC).isoformat(),
        "input_sha256": input_hashes,
        "source_spec": spec,
        "development_window": {
            "start": origin,
            "stop_exclusive": cutoff,
            "boundary_timezone": TIMEZONE,
        },
        "current_geometry": {
            **geometry_identity(current, zones),
            "crs": current.crs.to_string(),
            "coordinate_unit_to_m": current.crs.axis_info[0].unit_conversion_factor,
            "zip_member_timestamps": timestamps,
            "historical_eligibility": "Unverified before February 2026; audit only",
        },
        "older_geometry": {
            **geometry_identity(older, zones),
            "dataset_id": metadata["id"],
            "publication_date": pd.Timestamp(metadata["publicationDate"], unit="s", tz="UTC"),
            "rows_updated_at": pd.Timestamp(metadata["rowsUpdatedAt"], unit="s", tz="UTC"),
            "historical_eligibility": "Duplicate/missing IDs; no inferred remapping",
        },
        "graph": {
            "undirected_edges": len(edges),
            "intersecting_pairs": len(pairs),
            "isolated_zone_ids": nodes.loc[nodes.neighbor_count.eq(0), "zone_id"].tolist(),
            "max_degree": int(nodes.neighbor_count.max()),
            "maximum_overlap_m2": float(pairs.overlap_m2.max()),
            "eligible_for_full_development_ablation": False,
        },
        "borough_features": {
            "static": STATIC_FEATURES,
            "context": CONTEXT_FEATURES,
            "rows": len(features),
            "complete_feature_rows": len(usable),
            "min_target": usable.hour.min(),
            "max_target": usable.hour.max(),
            "borough_zone_counts": zones.groupby("borough").size().to_dict(),
            "temporal_columns_identical": True,
            "table_sha256": sha256(artifacts / "borough_features.parquet"),
            "feature_values_sha256": hashlib.sha256(
                pd.util.hash_pandas_object(
                    usable[["zone_id", "hour", *STATIC_FEATURES, *CONTEXT_FEATURES]], index=False
                )
                .to_numpy()
                .tobytes()
            ).hexdigest(),
        },
        "versions": {
            "geopandas": gpd.__version__,
            "shapely": shapely.__version__,
            "geos": shapely.geos_version_string,
        },
        "source_hashes": {
            str(p.relative_to(root)): sha256(p) for p in sorted((root / "src").rglob("*.py"))
        },
        "lockfile_sha256": sha256(root / "uv.lock"),
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
        "models_fitted": 0,
        "serving_model_changed": False,
        "test_metrics": None,
    }
    write_json(output / "metrics.json", result)
    write_json(root / "reports/latest_spatial_preparation.json", result)
    print(f"Spatial audit and borough features written to {output}", flush=True)
    print(
        f"{len(edges)} audited edges; {len(usable):,} borough feature rows; no fits",
        flush=True,
    )
    return result
