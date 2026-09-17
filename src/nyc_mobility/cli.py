"""One entry point for independently reproducible pipeline stages."""

import argparse

from nyc_mobility.config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=["download", "prepare", "train", "report", "audit-quality", "backtest", "all"],
    )
    parser.add_argument("--config", default="configs/default.toml")
    parser.add_argument("--protocol", default="configs/walk_forward.toml")
    args = parser.parse_args()
    config = load_config(args.config)
    if args.command == "backtest":
        from pathlib import Path

        from nyc_mobility.evaluation.backtest import run_backtest

        run_backtest(config, protocol_path=Path(args.protocol))
    if args.command == "audit-quality":
        from nyc_mobility.data.quality_audit import quality_audit

        quality_audit(config)
    if args.command in ("download", "all"):
        from nyc_mobility.data.download import acquire

        acquire(config["data"]["start"], config["data"]["end"])
    if args.command in ("prepare", "all"):
        from nyc_mobility.data.prepare import prepare

        prepare(config)
    if args.command in ("train", "all"):
        from nyc_mobility.models.train import train_models

        train_models(config)
    if args.command in ("report", "all"):
        from nyc_mobility.visualization.report import render_reports

        render_reports(config)


if __name__ == "__main__":
    main()
