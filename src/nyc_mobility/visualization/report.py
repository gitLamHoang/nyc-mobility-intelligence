"""Render reproducible development-period EDA and validation residual maps."""

import json
from pathlib import Path
from zipfile import ZipFile

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from nyc_mobility.config import TIMEZONE
from nyc_mobility.evaluation.metrics import metrics
from nyc_mobility.evaluation.splits import local_boundary


def render_reports(config: dict, root: Path = Path(".")) -> None:
    frame = pd.read_parquet(
        root / "data/processed/hourly_demand.parquet",
        filters=[("hour", "<", local_boundary(config["split"]["test_start"]))],
    )
    local = frame.hour.dt.tz_convert(TIMEZONE)
    frame["local_hour"], frame["weekday"] = local.dt.hour, local.dt.dayofweek
    figures = root / "reports/figures"
    figures.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "axes.spines.top": False,
            "axes.spines.right": False,
            "figure.dpi": 140,
        }
    )
    fig, axes = plt.subplots(1, 2, figsize=(12, 4), layout="constrained")
    daily = frame.groupby(local.dt.date).demand.sum()
    axes[0].plot(pd.to_datetime(daily.index), daily.values, color="#007c83", linewidth=1)
    axes[0].set(title="Recorded daily yellow-taxi pickups", ylabel="Pickups", xlabel="NYC date")
    axes[0].tick_params(axis="x", rotation=30)
    for weekend, label, color in [(False, "Weekday", "#007c83"), (True, "Weekend", "#cb6b22")]:
        values = frame.loc[(frame.weekday >= 5) == weekend].groupby("local_hour").demand.mean()
        axes[1].plot(values.index, values.values, label=label, color=color)
    axes[1].set(
        title="Hourly demand profile", xlabel="NYC local hour", ylabel="Mean pickups / zone"
    )
    axes[1].legend(frameon=False)
    fig.savefig(figures / "seasonality.png")
    plt.close(fig)
    totals = frame.groupby(["zone_id", "Zone", "borough"]).demand.sum().sort_values(ascending=False)
    totals.rename("pickups").to_csv(root / "reports/zone_demand.csv")
    fig, ax = plt.subplots(figsize=(8, 5), layout="constrained")
    top = totals.head(15).sort_values()
    ax.barh(top.index.get_level_values("Zone"), top.values, color="#007c83")
    ax.set(title="15 busiest pickup zones · development period", xlabel="Recorded pickups")
    fig.savefig(figures / "busiest_zones.png")
    plt.close(fig)

    predictions = pd.read_parquet(root / "artifacts/validation_predictions.parquet")
    experiment = json.loads((root / "reports/latest_experiment.json").read_text())
    champion = experiment["champion"]
    predictions["absolute_error"] = abs(predictions.demand - predictions[champion])
    predictions["residual"] = predictions[champion] - predictions.demand
    # Quantile boundaries are fitted on TRAIN only, then applied to validation actuals.
    train = frame.loc[frame.hour < local_boundary(config["split"]["validation_start"])]
    boundaries = np.unique(train.demand.quantile([0, 0.25, 0.5, 0.75, 0.9, 0.99, 1]).values)
    boundaries[0], boundaries[-1] = -np.inf, np.inf
    predictions["demand_band"] = pd.cut(predictions.demand, bins=boundaries).astype(str)
    slices = []
    for field in ("zone_id", "borough", "local_hour", "weekday", "rush_hour", "demand_band"):
        for label, group in predictions.groupby(field):
            slices.append(
                {
                    "dimension": field,
                    "value": label,
                    "rows": len(group),
                    **metrics(group.demand, group[champion]),
                }
            )
    pd.DataFrame(slices).to_csv(root / "reports/error_slices.csv", index=False)
    archive = (root / "data/external/taxi_zones.zip").resolve()
    with ZipFile(archive) as contents:
        shapefiles = [name for name in contents.namelist() if name.endswith(".shp")]
    if len(shapefiles) != 1:
        raise ValueError("Expected exactly one Taxi Zone shapefile in the archive")
    geometry = gpd.read_file(f"zip://{archive}!{shapefiles[0]}")
    geometry = geometry.rename(columns={"LocationID": "zone_id"}).dissolve(by="zone_id")
    geometry = geometry.loc[geometry.index.isin(frame.zone_id.unique())].to_crs(2263)
    values = frame.groupby("zone_id").demand.mean().rename("mean_pickups")
    errors = predictions.groupby("zone_id").absolute_error.mean().rename("mae")
    geometry = geometry.join(values).join(errors)
    if geometry[["mean_pickups", "mae"]].isna().any().any():
        raise ValueError("Geographic join has unmatched demand or error values")
    fig, axes = plt.subplots(1, 2, figsize=(12, 6), layout="constrained")
    geometry.plot(
        column="mean_pickups",
        ax=axes[0],
        cmap="YlGnBu",
        legend=True,
        legend_kwds={"label": "Mean pickups / hour", "shrink": 0.65},
    )
    geometry.plot(
        column="mae",
        ax=axes[1],
        cmap="YlOrRd",
        legend=True,
        legend_kwds={"label": "MAE (pickups)", "shrink": 0.65},
    )
    axes[0].set_title("NYC yellow-taxi pickup concentration")
    axes[1].set_title(f"April forecast errors · {champion}")
    for ax in axes:
        ax.set_axis_off()
    fig.savefig(figures / "demand_and_error_map.png")
    plt.close(fig)
    print(f"Reports written to {figures}", flush=True)
