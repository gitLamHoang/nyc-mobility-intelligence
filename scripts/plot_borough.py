"""Render saved borough ablation results, without refitting or reading trip records."""

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def render(directory: Path, output: Path) -> None:
    record = json.loads((directory / "metrics.json").read_text())
    comparisons = pd.read_csv(directory / "comparison.csv")
    slices = pd.read_csv(directory / "slice_metrics.csv")
    sparse = slices.loc[(slices.dimension == "zone_cohort") & (slices.value == "sparse")]
    plt.rcParams.update(
        {"axes.spines.top": False, "axes.spines.right": False, "font.family": "DejaVu Sans"}
    )
    fig, axes = plt.subplots(1, 2, figsize=(11, 5.2))
    fig.subplots_adjust(left=0.09, right=0.975, bottom=0.32, top=0.79, wspace=0.33)
    colors = {"borough_static": "#ce7a14", "borough_context": "#7254b5"}
    labels = {"borough_static": "Borough indicators", "borough_context": "Indicators + peer lags"}
    for offset, name in [(-0.18, "borough_static"), (0.18, "borough_context")]:
        values = (
            comparisons.loc[
                comparisons.candidate.eq(name) & comparisons.reference.eq("hist_gradient_boosting")
            ]
            .set_index("scope")
            .loc[["fold_1", "fold_2", "fold_3", "pooled"]]
        )
        axes[0].bar(
            np.arange(4) + offset,
            values.relative_reduction_pct,
            width=0.34,
            color=colors[name],
            label=labels[name],
        )
    axes[0].axhline(0, color="#596579", linewidth=1)
    axes[0].axvline(2.5, color="#b4bdc8", linewidth=1, linestyle=":")
    axes[0].set_xticks(range(4), ["Feb", "Mar", "Apr", "Pooled"])
    axes[0].set(
        title="Change versus temporal control", ylabel="MAE reduction (%) · higher is better"
    )
    axes[0].grid(axis="y", alpha=0.15)
    for name, label, color, style in [
        ("previous_week_168h", "Weekly baseline", "#6b7280", "--"),
        ("hist_gradient_boosting", "Temporal control", "#007c83", "-"),
        *[(n, labels[n], colors[n], "-") for n in colors],
    ]:
        rows = sparse.loc[sparse.model.eq(name)].sort_values("fold")
        axes[1].plot(
            range(3), rows.mae, marker="o", label=label, color=color, linestyle=style, linewidth=2
        )
    axes[1].set_xticks(range(3), ["February", "March", "April"])
    axes[1].set(
        title="Training-defined sparse zones", ylabel="MAE · pickups per zone-hour", ylim=(0, None)
    )
    axes[1].grid(axis="y", alpha=0.15)
    fig.suptitle("Borough features under matched chronological validation", fontsize=15, y=0.95)
    handles, names = axes[1].get_legend_handles_labels()
    fig.legend(
        handles, names, loc="lower center", bbox_to_anchor=(0.5, 0.14), ncol=2, frameon=False
    )
    fig.text(
        0.5,
        0.10,
        "Six fixed fits · 559,370 shared targets · 174-hour warm-up / six-hour embargo",
        ha="center",
        fontsize=10,
    )
    fig.text(
        0.5,
        0.058,
        "Peer counts use earlier hours only. "
        "Descriptive gains; no uncertainty intervals or promotion.",
        ha="center",
        fontsize=9,
    )
    fig.text(
        0.5,
        0.018,
        f"Official TLC data · {record['borough_id']} · May sealed",
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
    parser.add_argument("--output", type=Path, default=Path("reports/figures/borough.png"))
    args = parser.parse_args()
    render(args.report_directory, args.output)
