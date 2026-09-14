"""Configuration and artifact serialization shared by every pipeline stage."""

import json
import tomllib
from pathlib import Path

TIMEZONE = "America/New_York"


def load_config(path: str | Path = "configs/default.toml") -> dict:
    with Path(path).open("rb") as stream:
        config = tomllib.load(stream)
    if config["data"]["timezone"] != TIMEZONE or config["data"]["service"] != "yellow":
        raise ValueError("This pipeline currently supports NYC yellow taxis only")
    return config


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, default=str, allow_nan=False) + "\n")
