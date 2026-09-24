"""Render the audited current boundary graph; no historical modeling eligibility implied."""

import argparse
import json
from pathlib import Path
from zipfile import ZipFile

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from nyc_mobility.data.download import sha256


def render(directory: Path, output: Path) -> None:
    record = json.loads((directory / "metrics.json").read_text())
    archive = Path("data/external/taxi_zones.zip").resolve()
    if sha256(archive) != record["input_sha256"]["data/external/taxi_zones.zip"]:
        raise ValueError("Plot requires the audited geometry version")
    with ZipFile(archive) as contents:
        (member,) = [name for name in contents.namelist() if name.endswith(".shp")]
    geo = gpd.read_file(f"zip://{archive}!{member}").rename(columns={"LocationID": "zone_id"})
    nodes = pd.read_csv(directory / "zone_geometry.csv")
    geo = geo[["zone_id", "geometry"]].merge(nodes, on="zone_id", validate="one_to_one")
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 7.1), gridspec_kw={"width_ratios": [2, 1]})
    fig.subplots_adjust(left=0.02, right=0.95, top=0.80, bottom=0.24, wspace=0.16)
    geo.plot(
        column="neighbor_count",
        cmap="viridis",
        vmin=0,
        vmax=12,
        linewidth=0.3,
        edgecolor="white",
        ax=axes[0],
        legend=True,
        legend_kwds={"label": "Adjacent zones", "shrink": 0.78, "pad": 0.01},
    )
    isolated = geo.loc[geo.neighbor_count.eq(0)]
    isolated.representative_point().plot(ax=axes[0], color="#df5b32", markersize=28)
    axes[0].set_axis_off()
    counts = pd.Series(record["borough_features"]["borough_zone_counts"]).sort_values()
    axes[1].barh(counts.index, counts.values, color="#257b88", height=0.58)
    for position, value in enumerate(counts):
        axes[1].text(value + 1, position, str(value), va="center", fontsize=10)
    axes[1].set_xlim(0, 80)
    axes[1].set_xlabel("Zones in the 2024 lookup")
    axes[1].set_title("Borough feature coverage", fontsize=12)
    axes[1].spines[["top", "right", "left"]].set_visible(False)
    axes[1].tick_params(axis="y", length=0)
    fig.suptitle("Audit geography before using it in a historical forecast", fontsize=16, y=0.95)
    fig.text(
        0.5,
        0.86,
        "262 NYC zones · 604 undirected edges with ≥1 m shared boundary · 5 isolates in orange",
        ha="center",
        fontsize=11,
    )
    fig.text(
        0.5,
        0.13,
        "Current geometry: February 2026 snapshot, audit only. "
        "Older June 2025 source: duplicate/missing LocationIDs.",
        ha="center",
        fontsize=10,
    )
    fig.text(
        0.5,
        0.085,
        "Borough features use the older lookup and lagged other-zone counts. "
        "Boundary contact is not road connectivity.",
        ha="center",
        fontsize=10,
    )
    fig.text(
        0.5,
        0.035,
        f"Official TLC sources · {record['spatial_preparation_id']} · No fits; May sealed",
        ha="center",
        fontsize=9,
        color="#596579",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report_directory", type=Path)
    parser.add_argument("--output", type=Path, default=Path("reports/figures/spatial_audit.png"))
    args = parser.parse_args()
    render(args.report_directory, args.output)
