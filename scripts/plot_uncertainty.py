"""Plot saved conditional MAE intervals; no model fitting or observation access."""

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

LABELS = {
    "hist_gradient_boosting": "Squared error vs weekly baseline",
    "hist_gradient_boosting_poisson": "Poisson vs squared error",
    "hist_gradient_boosting_absolute": "Absolute error vs squared error",
}


def render(directory: Path, output: Path) -> None:
    record = json.loads((directory / "metrics.json").read_text())
    frame = pd.read_csv(directory / "comparison.csv")
    candidates = [contrast["candidate"] for contrast in record["protocol"]["contrasts"]]
    plt.rcParams.update(
        {"axes.spines.top": False, "axes.spines.right": False, "font.family": "DejaVu Sans"}
    )
    fig, axes = plt.subplots(1, len(candidates), figsize=(13, 4.8))
    fig.subplots_adjust(left=0.1, right=0.98, bottom=0.29, top=0.73, wspace=0.36)
    for ax, candidate in zip(axes, candidates, strict=True):
        part = frame.loc[frame.candidate == candidate].sort_values("block_days")
        for position, row in enumerate(part.itertuples()):
            color = "#007c83" if row.role == "primary" else "#9ba7b6"
            ax.hlines(position, row.delta_mae_low, row.delta_mae_high, color=color, linewidth=3)
            ax.plot(row.delta_mae, position, "o", color=color, markersize=6)
        ax.axvline(0, color="#596579", linestyle="--", linewidth=1)
        ax.set(
            title=LABELS.get(candidate, candidate), xlabel="MAE difference · candidate − reference"
        )
        ax.set_yticks(range(len(part)), [f"{b}-day blocks" for b in part.block_days])
        ax.set_ylim(-0.5, len(part) - 0.5)
        ax.invert_yaxis()
        ax.grid(axis="x", alpha=0.18)
        if candidate != candidates[0]:
            ax.set_yticklabels([])
    fig.suptitle(
        "Development MAE differences remain directional across block lengths", y=0.94, fontsize=15
    )
    fig.text(
        0.5,
        0.835,
        "Dots: observed difference  |  Bars: nominal 95% paired percentile intervals",
        ha="center",
        fontsize=11,
    )
    fig.text(
        0.5,
        0.15,
        "Negative favors candidate. Teal = primary 7-day setting. "
        "Horizontal scales differ by panel.",
        ha="center",
        fontsize=10,
    )
    fig.text(
        0.5,
        0.095,
        "Fixed fitted models and February–April month composition; no guarantee for future months.",
        ha="center",
        fontsize=10,
    )
    fig.text(
        0.5,
        0.035,
        f"Official TLC development errors · {record['uncertainty_id']} · May remains sealed",
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
    parser.add_argument("--output", type=Path, default=Path("reports/figures/uncertainty.png"))
    args = parser.parse_args()
    render(args.report_directory, args.output)
