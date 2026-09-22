"""Plot saved marginal and two-contrast-adjusted XGBoost MAE intervals."""

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.lines import Line2D


def render(directory: Path, output: Path) -> None:
    record = json.loads((directory / "metrics.json").read_text())
    table = pd.read_csv(directory / "comparison.csv")
    plt.rcParams.update(
        {"axes.spines.top": False, "axes.spines.right": False, "font.family": "DejaVu Sans"}
    )
    fig, axes = plt.subplots(1, 2, figsize=(11, 5.1))
    fig.subplots_adjust(left=0.145, right=0.975, bottom=0.32, top=0.76, wspace=0.4)
    for ax, depth in zip(axes, [4, 6], strict=True):
        subset = table.loc[table.candidate == f"xgboost_depth{depth}"].set_index("block_days")
        ax.axvline(0, color="#596579", linestyle="--", linewidth=1)
        for position, block in enumerate([1, 7, 14]):
            row = subset.loc[block]
            color = "#007c83" if row.role == "primary" else "#728296"
            ax.plot(
                [row.delta_mae_family_low, row.delta_mae_family_high],
                [position, position],
                color=color,
                linewidth=2,
            )
            ax.plot(
                [row.delta_mae_low, row.delta_mae_high],
                [position, position],
                color=color,
                linewidth=7,
                solid_capstyle="butt",
                alpha=0.55,
            )
            ax.plot(row.delta_mae, position, "o", color=color, markersize=6)
        ax.set_yticks(range(3), ["1 day", "7 days · primary", "14 days"])
        ax.set_ylim(-0.5, 2.5)
        ax.invert_yaxis()
        ax.set(title=f"XGBoost depth {depth} − histogram control", xlabel="MAE difference")
        ax.grid(axis="x", alpha=0.15)
    fig.suptitle("Small depth-6 MAE gain persists under paired resampling", fontsize=15, y=0.95)
    fig.text(
        0.5,
        0.835,
        "Negative favors XGBoost · Scales differ by panel · Zero shown as dashed line",
        ha="center",
        fontsize=10,
    )
    fig.legend(
        handles=[
            Line2D(
                [0], [0], color="#596579", linewidth=7, alpha=0.55, label="Marginal 95% interval"
            ),
            Line2D(
                [0],
                [0],
                color="#596579",
                linewidth=2,
                marker="o",
                label="97.5% per contrast · nominal 95% family of two",
            ),
        ],
        loc="lower center",
        bbox_to_anchor=(0.5, 0.16),
        frameon=False,
        ncol=2,
    )
    fig.text(
        0.5,
        0.12,
        "10,000 paired circular-day replicates per setting · "
        "Fixed February–April models and month composition",
        ha="center",
        fontsize=10,
    )
    fig.text(
        0.5,
        0.07,
        "Approximate conditional intervals; no guarantee for future months. "
        "RMSE tradeoff remains; no promotion.",
        ha="center",
        fontsize=9,
    )
    fig.text(
        0.5,
        0.025,
        f"Official TLC development errors · {record['uncertainty_id']} · May sealed",
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
        "--output", type=Path, default=Path("reports/figures/xgboost_uncertainty.png")
    )
    args = parser.parse_args()
    render(args.report_directory, args.output)
