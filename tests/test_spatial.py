"""Artificial geometry/count fixtures test contracts, not forecasting performance."""

import json
from zipfile import ZipFile

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Polygon, box

from nyc_mobility.data.download import sha256
from nyc_mobility.data.spatial import boundary_graph, geometry_identity, prepare_spatial
from nyc_mobility.features.borough import CONTEXT_FEATURES, STATIC_FEATURES, make_borough_features
from nyc_mobility.features.temporal import FEATURES, make_features

AVAILABLE = "2024-02-22T21:33:00Z"
POLICY = {"shared_boundary_min_m": 1.0, "maximum_pair_overlap_m2": 1.0}


def lookup():
    return pd.DataFrame(
        {
            "zone_id": [2, 3, 4],
            "borough": ["Queens", "Queens", "Manhattan"],
            "Zone": ["A", "B", "C"],
        }
    )


def panel():
    hours = pd.date_range("2026-03-01T00:00Z", periods=200, freq="h")
    p = pd.MultiIndex.from_product([[2, 3, 4], hours], names=["zone_id", "hour"]).to_frame(
        index=False
    )
    p["demand"] = np.tile(np.arange(200), 3) + p.zone_id * 10
    p["borough"] = p.zone_id.map(lookup().set_index("zone_id").borough)
    return p


def build(frame, **kwargs):
    return make_borough_features(frame, lookup(), lookup_available_at=AVAILABLE, **kwargs)


@pytest.mark.parametrize("delay", [0, 1, 3, 6])
def test_peer_means_exclude_focal_zone_and_respect_availability(delay):
    p = panel()
    f = build(p, observation_delay_hours=delay)
    target = pd.Timestamp("2026-03-08T12:00Z")
    rows = f.loc[f.hour.eq(target)].set_index("zone_id")
    index = int((target - p.hour.min()).total_seconds() / 3600)
    assert rows.loc[2, "borough_other_mean_lag_1"] == index - 1 - delay + 30
    assert rows.loc[2, "borough_other_mean_lag_24"] == index - 24 + 30
    assert rows.loc[3, "borough_other_mean_lag_1"] == index - 1 - delay + 20
    assert rows.loc[4, CONTEXT_FEATURES].eq(0).all()
    assert rows.borough_other_count.to_dict() == {2: 1, 3: 1, 4: 0}
    assert rows[STATIC_FEATURES].sum(axis=1).eq(1).all()
    assert f.loc[f.hour.eq(p.hour.min()), CONTEXT_FEATURES].isna().all().all()
    base = make_features(p, observation_delay_hours=delay)
    pd.testing.assert_frame_equal(f[list(base)], base)


@pytest.mark.parametrize("delay", [0, 1, 3, 6])
def test_contemporaneous_future_and_unavailable_tail_cannot_change_features(delay):
    p = panel()
    target = pd.Timestamp("2026-03-08T12:00Z")
    altered = p.copy()
    altered.loc[altered.hour >= target - pd.Timedelta(hours=delay), "demand"] += 100000
    cols = ["zone_id", "hour", *FEATURES[1:], *STATIC_FEATURES, *CONTEXT_FEATURES]
    before = build(p, observation_delay_hours=delay)
    after = build(altered, observation_delay_hours=delay)
    pd.testing.assert_frame_equal(
        before.loc[before.hour <= target, cols], after.loc[after.hour <= target, cols]
    )


def test_focal_zone_does_not_leak_into_its_own_peer_mean():
    p = panel()
    target = p.hour.max()
    altered = p.copy()
    altered.loc[altered.zone_id.eq(2), "demand"] += 1000
    a, b = build(p), build(altered)
    own = a.zone_id.eq(2) & a.hour.eq(target)
    other = a.zone_id.eq(3) & a.hour.eq(target)
    pd.testing.assert_frame_equal(a.loc[own, CONTEXT_FEATURES], b.loc[own, CONTEXT_FEATURES])
    np.testing.assert_allclose(
        b.loc[other, CONTEXT_FEATURES] - a.loc[other, CONTEXT_FEATURES], 1000
    )


@pytest.mark.parametrize(
    "defect",
    ["missing_zone", "missing_hour", "short_start", "short_end", "wrong_borough", "duplicate"],
)
def test_missing_peer_coverage_and_inconsistent_metadata_are_rejected(defect):
    p = panel()
    if defect == "missing_zone":
        p = p.loc[p.zone_id != 3]
    elif defect == "missing_hour":
        p = p.drop(index=250)
    elif defect == "short_start":
        p = p.drop(index=200)
    elif defect == "short_end":
        p = p.drop(index=399)
    elif defect == "wrong_borough":
        p.loc[0, "borough"] = "Bronx"
    else:
        p = pd.concat([p, p.iloc[[0]]])
    with pytest.raises(ValueError):
        build(p)


@pytest.mark.parametrize("date", ["2026-03-02T00:00Z", "2024-01-01"])
def test_lookup_must_be_available_with_explicit_timezone(date):
    with pytest.raises(ValueError, match="Lookup"):
        make_borough_features(panel(), lookup(), lookup_available_at=date)


def geometry():
    return gpd.GeoDataFrame(
        lookup(), geometry=[box(0, 0, 10, 10), box(10, 0, 20, 10), box(20, 10, 30, 20)], crs=2263
    )


def test_boundary_graph_uses_meters_excludes_point_contacts_and_has_no_self_edges():
    nodes, edges, pairs = boundary_graph(geometry(), lookup(), POLICY)
    assert edges[["zone_id", "neighbor_id"]].values.tolist() == [[2, 3]]
    assert edges.shared_boundary_m.iloc[0] == pytest.approx(10 * 1200 / 3937)
    assert nodes.neighbor_count.tolist() == [1, 1, 0]
    assert nodes.area_km2.iloc[0] == pytest.approx(100 * (1200 / 3937) ** 2 / 1e6)
    assert len(pairs) == 2
    assert pairs.loc[pairs.neighbor_id.eq(4), "qualifies"].eq(False).all()


@pytest.mark.parametrize(
    "defect",
    [
        "duplicate",
        "missing",
        "geographic_crs",
        "invalid",
        "empty",
        "null",
        "overlap",
        "borough",
        "tiny_boundary",
    ],
)
def test_geometry_fails_closed_or_excludes_submeter_contacts(defect):
    g = geometry()
    if defect == "duplicate":
        g.loc[1, "zone_id"] = 2
    elif defect == "missing":
        g = g.iloc[:2]
    elif defect == "geographic_crs":
        g = g.to_crs(4326)
    elif defect == "invalid":
        g.loc[0, "geometry"] = Polygon([(0, 0), (10, 10), (0, 10), (10, 0), (0, 0)])
    elif defect == "empty":
        g.loc[0, "geometry"] = Polygon()
    elif defect == "null":
        g.loc[0, "geometry"] = None
    elif defect == "overlap":
        g.loc[1, "geometry"] = box(5, 0, 15, 10)
    elif defect == "borough":
        g.loc[0, "borough"] = "Bronx"
    else:
        g.loc[1, "geometry"] = box(10, 9, 20, 10)
        _, edges, _ = boundary_graph(g, lookup(), POLICY)
        assert edges.empty
        return
    with pytest.raises(ValueError):
        boundary_graph(g, lookup(), POLICY)


def test_identity_audit_reports_older_ids_without_guessing_remapping():
    g = geometry()
    g.loc[1, "zone_id"] = 2
    audit = geometry_identity(g, lookup())
    assert audit["duplicate_zone_ids"] == {"2": 2}
    assert audit["missing_nyc_zone_ids"] == [3]
    assert not audit["one_to_one_nyc_mapping"]


def test_real_stage_shape_excludes_test_targets_and_preserves_existing_files(tmp_path, monkeypatch):
    ext = tmp_path / "data/external"
    ext.mkdir(parents=True)
    lookup().rename(columns={"zone_id": "LocationID", "borough": "Borough"}).to_csv(
        ext / "taxi_zone_lookup.csv", index=False
    )
    shape_dir = tmp_path / "shapes"
    shape_dir.mkdir()
    geometry().rename(columns={"zone_id": "LocationID"}).to_file(shape_dir / "zones.shp")
    with ZipFile(ext / "taxi_zones.zip", "w") as archive:
        for p in shape_dir.iterdir():
            archive.write(p, "nested/" + p.name)
    old = geometry().rename(columns={"zone_id": "locationid"})
    old.loc[1, "locationid"] = 2
    old.to_file(ext / "taxi_zones_opendata.geojson", driver="GeoJSON")
    (ext / "taxi_zones_opendata_metadata.json").write_text(
        json.dumps(
            {"id": "artificial-only", "publicationDate": 1700000000, "rowsUpdatedAt": 1700000000}
        )
    )
    spec = tmp_path / "spatial.toml"
    lines = [
        "[policy]",
        "shared_boundary_min_m = 1.0",
        "maximum_pair_overlap_m2 = 1.0",
        f'lookup_available_at = "{AVAILABLE}"',
    ]
    for p in sorted(ext.iterdir()):
        lines += [
            "[[assets]]",
            f'file = "{p.relative_to(tmp_path)}"',
            'url = "https://example.invalid/never-requested"',
            f'sha256 = "{sha256(p)}"',
        ]
    spec.write_text("\n".join(lines))
    data = tmp_path / "data/processed/hourly_demand.parquet"
    data.parent.mkdir()
    p = panel()
    p.loc[p.hour >= pd.Timestamp("2026-03-09T04:00Z"), "demand"] = np.nan
    p.to_parquet(data, index=False)
    (tmp_path / "uv.lock").write_text("artificial-lock")
    serving = tmp_path / "artifacts/model.joblib"
    serving.parent.mkdir()
    serving.write_bytes(b"preserve")
    report = tmp_path / "reports/latest_xgboost.json"
    report.parent.mkdir()
    report.write_text("preserve")

    def forbidden(*args, **kwargs):
        raise AssertionError("cached sources must not be downloaded")

    monkeypatch.setattr("nyc_mobility.data.spatial.fetch", forbidden)
    result = prepare_spatial(
        {"split": {"train_start": "2026-03-01", "test_start": "2026-03-09"}}, tmp_path, spec
    )
    assert result["models_fitted"] == 0 and result["test_metrics"] is None
    assert result["older_geometry"]["duplicate_zone_ids"] == {"2": 2}
    assert result["graph"]["eligible_for_full_development_ablation"] is False
    assert result["borough_features"]["temporal_columns_identical"] is True
    saved = pd.read_parquet(
        tmp_path
        / "artifacts/spatial_preparation"
        / result["spatial_preparation_id"]
        / "borough_features.parquet"
    )
    assert saved.hour.max() < pd.Timestamp("2026-03-09T04:00Z")
    assert serving.read_bytes() == b"preserve" and report.read_text() == "preserve"
    # A citywide truncated final hour must not silently shorten the requested window.
    p.loc[p.hour != pd.Timestamp("2026-03-09T03:00Z")].to_parquet(data, index=False)
    with pytest.raises(ValueError, match="coverage"):
        prepare_spatial(
            {"split": {"train_start": "2026-03-01", "test_start": "2026-03-09"}}, tmp_path, spec
        )
    # Hash rejection happens before loading tables or modifying evidence.
    with (ext / "taxi_zone_lookup.csv").open("a") as f:
        f.write("\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        prepare_spatial(
            {"split": {"train_start": "2026-03-01", "test_start": "2026-03-09"}}, tmp_path, spec
        )
