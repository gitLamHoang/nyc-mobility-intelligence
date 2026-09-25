"""Plot the three saved borough MAE contrasts and conditional uncertainty intervals."""

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.ticker import MaxNLocator

CONTRASTS = {
    ("borough_static", "hist_gradient_boosting"): "Static borough indicators\n− temporal control",
    ("borough_context", "hist_gradient_boosting"): "Lagged borough context\n− temporal control",
    ("borough_context", "borough_static"): "Lagged borough context\n− static indicators",
}
BLOCKS = [7, 1, 14]
INTERVAL_COLUMNS = [
    "delta_mae",
    "delta_mae_low",
    "delta_mae_high",
    "delta_mae_family_low",
    "delta_mae_family_high",
]


def render(directory: Path, output: Path) -> None:
    record = json.loads((directory / "metrics.json").read_text())
    table = pd.read_csv(directory / "comparison.csv")
    study = record["protocol"]["study"]
    expected_keys = {
        (candidate, reference, block) for candidate, reference in CONTRASTS for block in BLOCKS
    }
    keys = list(zip(table.candidate, table.reference, table.block_days, strict=True))
    if len(keys) != len(expected_keys) or set(keys) != expected_keys:
        raise ValueError("Expected exactly three borough contrasts at 7-, 1-, and 14-day blocks")
    if (
        study["primary_block_days"] != 7
        or set(study["sensitivity_block_days"]) != {1, 14}
        or study["family_size"] != 3
        or study["family_method"] != "bonferroni"
        or study["family_metric"] != "delta_mae"
        or not np.isclose(study["confidence_level"], 0.95)
        or not np.isclose(study["family_confidence_level"], 0.95)
        or not (table.family_method == "bonferroni").all()
        or not (table.family_metric == "delta_mae").all()
        or not (table.family_size == 3).all()
        or not np.allclose(table.confidence_level, 0.95)
        or not np.allclose(table.family_confidence_level, 0.95)
        or not np.allclose(table.per_contrast_confidence_level, 1 - 0.05 / 3)
        or not (table.role == np.where(table.block_days == 7, "primary", "sensitivity")).all()
    ):
        raise ValueError("The report does not match the frozen borough interval definitions")
    if not np.isfinite(table[INTERVAL_COLUMNS].to_numpy()).all():
        raise ValueError("MAE estimates and interval endpoints must be finite")
    if not (
        (table.delta_mae_family_low <= table.delta_mae_low)
        & (table.delta_mae_low <= table.delta_mae_high)
        & (table.delta_mae_high <= table.delta_mae_family_high)
    ).all():
        raise ValueError("Expected ordered marginal intervals inside the adjusted intervals")
    plt.rcParams.update(
        {"axes.spines.top": False, "axes.spines.right": False, "font.family": "DejaVu Sans"}
    )
    fig, axes = plt.subplots(1, 3, figsize=(13.8, 5.8), sharex=True, sharey=True)
    fig.subplots_adjust(left=0.145, right=0.98, bottom=0.35, top=0.72, wspace=0.22)
    low = min(0, table.delta_mae_family_low.min(), table.delta_mae.min())
    high = max(0, table.delta_mae_family_high.max(), table.delta_mae.max())
    padding = max((high - low) * 0.12, 0.0001)
    for ax, ((candidate, reference), title) in zip(axes, CONTRASTS.items(), strict=True):
        subset = table.loc[
            (table.candidate == candidate) & (table.reference == reference)
        ].set_index("block_days")
        ax.axhspan(-0.38, 0.38, color="#e7f3f1", zorder=0)
        ax.axvline(0, color="#596579", linestyle="--", linewidth=1, zorder=1)
        for position, block in enumerate(BLOCKS):
            row = subset.loc[block]
            color = "#007c83" if block == 7 else "#62758a"
            ax.hlines(
                position,
                row.delta_mae_family_low,
                row.delta_mae_family_high,
                color=color,
                linewidth=1.8,
                zorder=2,
            )
            ax.vlines(
                [row.delta_mae_family_low, row.delta_mae_family_high],
                position - 0.065,
                position + 0.065,
                color=color,
                linewidth=1.5,
                zorder=2,
            )
            ax.hlines(
                position,
                row.delta_mae_low,
                row.delta_mae_high,
                color=color,
                linewidth=7,
                alpha=0.55,
                zorder=3,
            )
            ax.plot(row.delta_mae, position, "o", color=color, markersize=6, zorder=4)
        ax.set_yticks(
            range(3), ["7 days · primary", "1 day · sensitivity", "14 days · sensitivity"]
        )
        ax.set_ylim(2.5, -0.5)
        ax.set_xlim(low - padding, high + padding)
        ax.set_title(title, fontsize=11, pad=14)
        ax.xaxis.set_major_locator(MaxNLocator(nbins=4))
        ax.ticklabel_format(axis="x", style="plain", useOffset=False)
        ax.grid(axis="x", alpha=0.15)
    fig.suptitle("Borough features: paired uncertainty on development months", fontsize=16, y=0.955)
    fig.text(
        0.5,
        0.865,
        "Negative favors the first model in each panel · Shared horizontal scale · "
        "Dashed line marks no difference",
        ha="center",
        fontsize=10,
    )
    fig.text(
        0.56,
        0.27,
        "MAE difference · candidate − reference (pickups per zone-hour)",
        ha="center",
        fontsize=10,
    )
    fig.legend(
        handles=[
            Line2D(
                [0], [0], color="#596579", marker="o", linestyle="none", label="Observed difference"
            ),
            Line2D(
                [0], [0], color="#596579", linewidth=7, alpha=0.55, label="Marginal 95% interval"
            ),
            Line2D(
                [0],
                [0],
                color="#596579",
                linewidth=1.8,
                marker="|",
                markersize=8,
                label="Bonferroni 98.333…% per-contrast interval",
            ),
        ],
        loc="lower center",
        bbox_to_anchor=(0.5, 0.175),
        frameon=False,
        ncol=3,
        fontsize=9,
    )
    fig.text(
        0.5,
        0.145,
        "Nominal 95% family coverage for the three MAE contrasts within each block setting; "
        "not across block settings.",
        ha="center",
        fontsize=9,
    )
    fig.text(
        0.5,
        0.10,
        f"{study['replicates']:,} paired circular-day replicates per setting · "
        "Fixed February–April models and month composition",
        ha="center",
        fontsize=9,
    )
    fig.text(
        0.5,
        0.055,
        "Approximate conditional intervals do not cover prior model selection or guarantee "
        "future-month performance.",
        ha="center",
        fontsize=9,
    )
    fig.text(
        0.5,
        0.01,
        f"Official TLC development errors · {record['uncertainty_id']} · May test not included",
        ha="center",
        fontsize=8,
        color="#596579",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report_directory", type=Path)
    parser.add_argument(
        "--output", type=Path, default=Path("reports/figures/borough_uncertainty.png")
    )
    args = parser.parse_args()
    render(args.report_directory, args.output)
