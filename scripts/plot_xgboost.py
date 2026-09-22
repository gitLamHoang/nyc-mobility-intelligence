"""Render the frozen XGBoost comparison from saved metrics without fitting."""

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


def render(directory: Path, output: Path) -> None:
    record = json.loads((directory / "metrics.json").read_text())
    folds = pd.read_csv(directory / "fold_metrics.csv")
    slices = pd.read_csv(directory / "slice_metrics.csv")
    sparse = slices.loc[(slices.dimension == "zone_cohort") & (slices.value == "sparse")]
    plt.rcParams.update(
        {"axes.spines.top": False, "axes.spines.right": False, "font.family": "DejaVu Sans"}
    )
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.8))
    fig.subplots_adjust(bottom=0.3, top=0.8, wspace=0.3)
    candidates = [
        ("previous_week_168h", "Weekly baseline", "#6b7280", "--"),
        ("hist_gradient_boosting", "Histogram control", "#007c83", "-"),
        ("xgboost_depth4", "XGBoost depth 4", "#ce7a14", "-"),
        ("xgboost_depth6", "XGBoost depth 6", "#7254b5", "-"),
    ]
    for ax, data, title in zip(
        axes, [folds, sparse], ["All zone-hours", "Training-defined sparse zones"], strict=True
    ):
        for name, label, color, style in candidates:
            values = data.loc[data.model == name].sort_values("fold")
            ax.plot(
                range(3),
                values.mae,
                marker="o",
                label=label,
                color=color,
                linestyle=style,
                linewidth=2,
            )
        ax.set(title=title, ylabel="MAE · pickups per zone-hour", ylim=(0, None))
        ax.set_xticks(range(3), ["February", "March", "April"])
        ax.grid(axis="y", alpha=0.2)
    fig.suptitle("A bounded XGBoost comparison", fontsize=15, y=0.95)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(
        handles, labels, loc="lower center", bbox_to_anchor=(0.5, 0.12), ncol=2, frameon=False
    )
    fig.text(
        0.5,
        0.08,
        f"{record['validation_rows']:,} shared targets · "
        "174-hour warm-up / six-hour training embargo · Lower is better.",
        ha="center",
        fontsize=9,
    )
    fig.text(
        0.5,
        0.025,
        f"Official TLC data · {record['xgboost_id']} · Development results; May sealed",
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
    parser.add_argument("--output", type=Path, default=Path("reports/figures/xgboost.png"))
    args = parser.parse_args()
    render(args.report_directory, args.output)
