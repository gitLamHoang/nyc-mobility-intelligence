"""Stream official TLC assets to disk; verify cached files with SHA-256."""

import argparse
import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pandas as pd
import pyarrow.parquet as pq

from nyc_mobility.config import write_json

BASE = "https://d37ci6vzurychx.cloudfront.net"


def months(start: str, end: str) -> list[str]:
    first, last = pd.Period(start, freq="M"), pd.Period(end, freq="M")
    if first > last:
        raise ValueError("start month must not follow end month")
    return [str(value) for value in pd.period_range(first, last, freq="M")]


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def fetch(url: str, destination: Path) -> dict:
    """Only replace a destination after a complete, structurally valid download."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    sidecar = destination.with_suffix(destination.suffix + ".json")
    if destination.exists() and sidecar.exists():
        info = json.loads(sidecar.read_text())
        if info["url"] == url and sha256(destination) == info["sha256"]:
            print(f"Cache verified: {destination.name}", flush=True)
            return info
    temporary = destination.with_suffix(destination.suffix + ".part")
    for attempt in range(3):
        try:
            with httpx.stream("GET", url, timeout=120, follow_redirects=True) as response:
                response.raise_for_status()
                with temporary.open("wb") as stream:
                    for block in response.iter_bytes(1024 * 1024):
                        stream.write(block)
                expected = response.headers.get("content-length")
                if expected and temporary.stat().st_size != int(expected):
                    raise OSError("Incomplete download")
                info = {
                    "url": url,
                    "file": str(destination),
                    "bytes": temporary.stat().st_size,
                    "sha256": sha256(temporary),
                    "downloaded_at": datetime.now(UTC).isoformat(),
                    "etag": response.headers.get("etag"),
                    "last_modified": response.headers.get("last-modified"),
                }
            if destination.suffix == ".parquet":
                info["rows"] = pq.ParquetFile(temporary).metadata.num_rows
            temporary.replace(destination)
            write_json(sidecar, info)
            print(f"Downloaded: {destination.name} ({info['bytes']:,} bytes)", flush=True)
            return info
        except (httpx.HTTPError, OSError):
            temporary.unlink(missing_ok=True)
            if attempt == 2:
                raise
            time.sleep(2**attempt)
    raise RuntimeError("Download exhausted retries")


def acquire(start: str, end: str, root: Path = Path(".")) -> list[dict]:
    manifest = []
    for month in months(start, end):
        name = f"yellow_tripdata_{month}.parquet"
        manifest.append(fetch(f"{BASE}/trip-data/{name}", root / "data/raw" / name))
    for name in ("taxi_zone_lookup.csv", "taxi_zones.zip"):
        manifest.append(fetch(f"{BASE}/misc/{name}", root / "data/external" / name))
    write_json(root / "reports/data_manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2025-12")
    parser.add_argument("--end", default="2026-05")
    args = parser.parse_args()
    acquire(args.start, args.end)
