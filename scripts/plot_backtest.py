"""Plot immutable backtest summaries without loading observations or fitting models."""

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

MODELS = {
    "previous_week_168h": ("Weekly baseline", "#596579"),
    "hist_gradient_boosting": ("Squared error", "#007c83"),
    "hist_gradient_boosting_poisson": ("Poisson", "#cb6b22"),
    "hist_gradient_boosting_absolute": ("Absolute error", "#7757a0"),
}


def render(directory: Path, output: Path) -> None:
    record = json.loads((directory / "metrics.json").read_text())
    folds = pd.read_csv(directory / "fold_metrics.csv")
    slices = pd.read_csv(directory / "slice_metrics.csv")
    sparse = slices.loc[(slices.dimension == "zone_cohort") & (slices.value == "sparse")]
    order = [fold["name"] for fold in record["folds"]]
    months = [
        pd.Timestamp(fold["validation_start"]).tz_convert("America/New_York").strftime("%b %Y")
        for fold in record["folds"]
    ]
    plt.rcParams.update(
        {"axes.spines.top": False, "axes.spines.right": False, "font.family": "DejaVu Sans"}
    )
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 5.3))
    fig.subplots_adjust(bottom=0.27, top=0.8, wspace=0.3)
    for ax, frame, title in zip(
        axes, [folds, sparse], ["All 262 zones", "Sparse zones only"], strict=True
    ):
        for model, (label, color) in MODELS.items():
            values = frame.loc[frame.model == model].set_index("fold").loc[order, "mae"]
            ax.plot(months, values, marker="o", linewidth=2, color=color, label=label)
        ax.set(title=title, ylabel="MAE · pickups per zone-hour", ylim=(0, None))
        ax.grid(axis="y", alpha=0.2)
    fig.suptitle("Boosting loss comparison across expanding validation folds", fontsize=15, y=0.95)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(
        handles, labels, loc="lower center", bbox_to_anchor=(0.5, 0.115), ncol=4, frameon=False
    )
    fig.text(
        0.5,
        0.07,
        "Sparse = training mean ≤1 pickup/hour, defined separately in each fold. Lower is better.",
        ha="center",
        fontsize=10,
    )
    fig.text(
        0.5,
        0.025,
        f"Official TLC data · {record['backtest_id']} · Development comparison; May remains sealed",
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
    parser.add_argument(
        "--output", type=Path, default=Path("reports/figures/walk_forward_losses.png")
    )
    args = parser.parse_args()
    render(args.report_directory, args.output)
