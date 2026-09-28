"""Render descriptive weather comparisons from compact CSVs only, without model fits."""

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

CANDIDATES = ["weather_3h", "weather_6h"]
LABELS = {
    "hist_gradient_boosting": "Temporal control",
    "weather_3h": "Weather 3h · primary",
    "weather_6h": "Weather 6h · sensitivity",
}
COLORS = {"hist_gradient_boosting": "#596579", "weather_3h": "#007c83", "weather_6h": "#ce7a14"}


def render(directory: Path, output: Path) -> None:
    fold_scores = pd.read_csv(directory / "fold_metrics.csv")
    comparisons = pd.read_csv(directory / "comparison.csv")
    slices = pd.read_csv(directory / "slice_metrics.csv")
    days = pd.read_csv(directory / "daily_mae.csv")
    folds = ["fold_1", "fold_2", "fold_3"]
    plt.rcParams.update(
        {"axes.spines.top": False, "axes.spines.right": False, "font.family": "DejaVu Sans"}
    )
    fig, axes = plt.subplots(1, 3, figsize=(14, 5.5))
    fig.subplots_adjust(left=0.065, right=0.98, bottom=0.32, top=0.78, wspace=0.40)
    for name in ["hist_gradient_boosting", *CANDIDATES]:
        rows = fold_scores.loc[fold_scores.model.eq(name)].set_index("fold").loc[folds]
        axes[0].plot(
            np.arange(3),
            rows.mae,
            marker="o",
            color=COLORS[name],
            label=LABELS[name],
            linewidth=2,
            linestyle="--" if name == "hist_gradient_boosting" else "-",
        )
    axes[0].set_xticks(range(3), ["February", "March", "April"])
    axes[0].set(
        title="Monthly development error", ylabel="MAE · pickups per zone-hour", ylim=(0, None)
    )
    axes[0].grid(axis="y", alpha=0.15)

    pooled = (
        comparisons.loc[
            comparisons.scope.eq("pooled") & comparisons.reference.eq("hist_gradient_boosting")
        ]
        .set_index("candidate")
        .loc[CANDIDATES]
    )
    axes[1].bar(range(2), pooled.delta_mae, color=[COLORS[name] for name in CANDIDATES], width=0.6)
    axes[1].set_xticks(range(2), ["3h primary", "6h sensitivity"])
    axes[1].axhline(0, color="#596579", linewidth=1)
    axes[1].set(title="Pooled change versus control", ylabel="MAE difference · lower is better")
    axes[1].grid(axis="y", alpha=0.15)
    for index, value in enumerate(pooled.delta_mae):
        axes[1].annotate(
            f"{value:+.4f}",
            (index, value),
            xytext=(0, 5 if value >= 0 else -13),
            textcoords="offset points",
            ha="center",
            fontsize=10,
        )
    axes[1].margins(y=0.22)

    cohort_changes = {}
    for dimension, value in [("zone_cohort", "sparse"), ("target_cohort", "zero")]:
        selected = slices.loc[slices.dimension.eq(dimension) & slices.value.eq(value)]
        means, counts = {}, {}
        for name in ["hist_gradient_boosting", *CANDIDATES]:
            rows = selected.loc[selected.model.eq(name)].set_index("fold").loc[folds]
            means[name] = np.average(rows.mae, weights=rows.rows)
            counts[name] = rows.rows.sum()
        if len(set(counts.values())) != 1:
            raise ValueError("Candidate/control cohort coverage differs")
        cohort_changes[value] = {
            name: means[name] - means["hist_gradient_boosting"] for name in CANDIDATES
        }
    for offset, name in zip([-0.18, 0.18], CANDIDATES, strict=True):
        axes[2].bar(
            np.arange(2) + offset,
            [cohort_changes[cohort][name] for cohort in ["sparse", "zero"]],
            width=0.34,
            color=COLORS[name],
        )
    axes[2].set_xticks(range(2), ["Sparse zones", "Zero targets"])
    axes[2].axhline(0, color="#596579", linewidth=1)
    axes[2].set(title="Pooled sparse / zero change", ylabel="MAE difference · lower is better")
    axes[2].grid(axis="y", alpha=0.15)
    axes[2].margins(y=0.15)

    target_count = int(days.loc[days.model.eq("hist_gradient_boosting"), "rows"].sum())
    fig.suptitle("Weather under matched chronological validation", fontsize=16, y=0.96)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(
        handles, labels, loc="lower center", bbox_to_anchor=(0.5, 0.175), ncol=3, frameon=False
    )
    fig.text(
        0.5,
        0.135,
        f"Six fixed fits · {target_count:,} shared targets · "
        "174-hour warm-up / six-hour label embargo",
        ha="center",
        fontsize=10,
    )
    fig.text(
        0.5,
        0.092,
        "Conditional retrospective NOAA archive: weather publication delay is assumed. "
        "Sparse cohorts use training data only.",
        ha="center",
        fontsize=9,
    )
    fig.text(
        0.5,
        0.052,
        "Descriptive comparisons; no significance claim or model promotion. "
        "Missing weather and unverified quality flags retained.",
        ha="center",
        fontsize=9,
    )
    fig.text(
        0.5,
        0.016,
        f"Official TLC / NOAA data · {directory.name} · May sealed",
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
    parser.add_argument("--output", type=Path, default=Path("reports/figures/weather_ablation.png"))
    args = parser.parse_args()
    render(args.report_directory, args.output)
