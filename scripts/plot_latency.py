"""Render saved latency study metrics without reading targets or refitting models."""

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


def render(directory: Path, output: Path) -> None:
    record = json.loads((directory / "metrics.json").read_text())
    scores = pd.read_csv(directory / "pooled_metrics.csv")
    model = record["protocol"]["study"]["model"]
    plt.rcParams.update(
        {"axes.spines.top": False, "axes.spines.right": False, "font.family": "DejaVu Sans"}
    )
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.8))
    fig.subplots_adjust(bottom=0.3, top=0.8, wspace=0.3)
    for ax, metric, title in zip(axes, ["mae", "rmse"], ["Pooled MAE", "Pooled RMSE"], strict=True):
        for name, label, color, style in [
            (model, "Squared-error boosting", "#007c83", "-"),
            ("previous_week_168h", "Weekly baseline", "#596579", "--"),
        ]:
            values = scores.loc[scores.model == name].sort_values("delay_hours")
            ax.plot(
                values.delay_hours,
                values[metric],
                marker="o",
                label=label,
                color=color,
                linestyle=style,
                linewidth=2,
            )
        ax.set(
            title=title,
            xlabel="Additional observation delay · elapsed hours",
            ylabel="Pickups per zone-hour",
            ylim=(0, None),
        )
        ax.set_xticks(record["protocol"]["study"]["delay_hours"])
        ax.grid(axis="y", alpha=0.2)
    fig.suptitle("Forecast accuracy with delayed pickup observations", fontsize=15, y=0.95)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(
        handles, labels, loc="lower center", bbox_to_anchor=(0.5, 0.14), ncol=2, frameon=False
    )
    fig.text(
        0.5,
        0.09,
        f"Same {record['validation_rows_per_setting']:,} February–April zone-hours per setting; "
        "matched training targets. Lower is better.",
        ha="center",
        fontsize=9,
    )
    fig.text(
        0.5,
        0.035,
        f"Official TLC data · {record['latency_id']} · May sealed; no live-feed claim",
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
    parser.add_argument("--output", type=Path, default=Path("reports/figures/latency.png"))
    args = parser.parse_args()
    render(args.report_directory, args.output)
