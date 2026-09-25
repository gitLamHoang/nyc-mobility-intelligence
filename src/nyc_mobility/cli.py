"""One entry point for independently reproducible pipeline stages."""

import argparse

from nyc_mobility.config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=[
            "download",
            "prepare",
            "train",
            "report",
            "audit-quality",
            "backtest",
            "uncertainty",
            "latency",
            "xgboost",
            "xgboost-uncertainty",
            "spatial-prepare",
            "borough",
            "borough-uncertainty",
            "all",
        ],
    )
    parser.add_argument("--config", default="configs/default.toml")
    parser.add_argument("--protocol", help="Optional study protocol TOML")
    args = parser.parse_args()
    config = load_config(args.config)
    if args.command == "backtest":
        from pathlib import Path

        from nyc_mobility.evaluation.backtest import run_backtest

        run_backtest(config, protocol_path=Path(args.protocol or "configs/walk_forward.toml"))
    if args.command == "uncertainty":
        from pathlib import Path

        from nyc_mobility.evaluation.uncertainty import run_uncertainty

        run_uncertainty(config, protocol_path=Path(args.protocol or "configs/uncertainty.toml"))
    if args.command == "latency":
        from pathlib import Path

        from nyc_mobility.evaluation.latency import run_latency

        run_latency(config, protocol_path=Path(args.protocol or "configs/latency.toml"))
    if args.command == "xgboost":
        from pathlib import Path

        from nyc_mobility.evaluation.xgboost import run_xgboost

        run_xgboost(config, protocol_path=Path(args.protocol or "configs/xgboost.toml"))
    if args.command == "xgboost-uncertainty":
        from pathlib import Path

        from nyc_mobility.evaluation.xgboost_uncertainty import run_xgboost_uncertainty

        run_xgboost_uncertainty(
            config, protocol_path=Path(args.protocol or "configs/xgboost_uncertainty.toml")
        )
    if args.command == "spatial-prepare":
        from pathlib import Path

        from nyc_mobility.data.spatial import prepare_spatial

        prepare_spatial(config, spec_path=Path(args.protocol or "configs/spatial_inputs.toml"))
    if args.command == "borough":
        from pathlib import Path

        from nyc_mobility.evaluation.borough import run_borough

        run_borough(config, protocol_path=Path(args.protocol or "configs/borough_spatial.toml"))
    if args.command == "borough-uncertainty":
        from pathlib import Path

        from nyc_mobility.evaluation.borough_uncertainty import run_borough_uncertainty

        run_borough_uncertainty(
            config, protocol_path=Path(args.protocol or "configs/borough_uncertainty.toml")
        )
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
