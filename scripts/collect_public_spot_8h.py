"""Collect auditable Binance Spot 8h candles for offline development research.

No credentials, exchange trading methods, or forward filling are used.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT")
STEP_MS = 8 * 60 * 60 * 1000
BASE = "https://api.binance.com/api/v3/klines"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fetch(symbol: str, start_ms: int, end_ms: int, raw_path: Path) -> list[list]:
    cursor = start_ms
    rows: list[list] = []
    with raw_path.open("xb") as output:
        while cursor < end_ms:
            query = urllib.parse.urlencode({"symbol": symbol, "interval": "8h", "startTime": cursor,
                                            "endTime": end_ms - 1, "limit": 1000})
            request = urllib.request.Request(f"{BASE}?{query}", headers={"User-Agent": "orderflow-edge-lab-research/1"})
            for attempt in range(5):
                try:
                    with urllib.request.urlopen(request, timeout=45) as response:
                        payload = response.read()
                    page = json.loads(payload)
                    break
                except (OSError, ValueError):
                    if attempt == 4:
                        raise
                    time.sleep(2 ** attempt)
            output.write(payload + b"\n")  # exact response bytes, one HTTP page per line
            if not page:
                break
            rows.extend(page)
            new_cursor = int(page[-1][0]) + STEP_MS
            if new_cursor <= cursor:
                raise ValueError(f"{symbol}: non-advancing Binance page")
            cursor = new_cursor
            time.sleep(0.08)
    return rows


def validate(rows: list[list], symbol: str) -> dict:
    if not rows:
        raise ValueError(f"{symbol}: no spot candles")
    opens = [int(row[0]) for row in rows]
    gaps = [(opens[i - 1], opens[i]) for i in range(1, len(opens)) if opens[i] - opens[i - 1] != STEP_MS]
    for row in rows:
        if len(row) < 6 or int(row[0]) % STEP_MS or min(float(row[j]) for j in (1, 2, 3, 4)) <= 0:
            raise ValueError(f"{symbol}: invalid 8h OHLCV candle")
    return {"first_open_utc": timestamp(opens[0]), "last_open_utc": timestamp(opens[-1]),
            "bars": len(rows), "gaps": [[timestamp(a), timestamp(b)] for a, b in gaps]}


def timestamp(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat().replace("+00:00", "Z")


def collect(output: Path, start: str, end: str) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    raw_dir = output / "raw"
    csv_dir = output / "aligned_csv"
    raw_dir.mkdir(exist_ok=True)
    csv_dir.mkdir(exist_ok=True)
    start_ms = int(datetime.fromisoformat(start.replace("Z", "+00:00")).timestamp() * 1000)
    end_ms = int(datetime.fromisoformat(end.replace("Z", "+00:00")).timestamp() * 1000)
    retrieved = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    data = {}
    meta = {}
    for symbol in SYMBOLS:
        raw_path = raw_dir / f"{symbol}-8h.jsonl"
        rows = fetch(symbol, start_ms, end_ms, raw_path)
        info = validate(rows, symbol)
        info.update({"raw_file": str(raw_path.relative_to(output)).replace("\\", "/"),
                     "raw_sha256": digest(raw_path), "requested_start_utc": start,
                     "requested_end_exclusive_utc": end})
        data[symbol] = {int(row[0]): row for row in rows}
        meta[symbol] = info
        print(symbol, info, flush=True)
    common_start = max(min(frame) for frame in data.values())
    common_end = min(max(frame) for frame in data.values())
    grid = range(common_start, common_end + STEP_MS, STEP_MS)
    for symbol, frame in data.items():
        missing = [timestamp(t) for t in grid if t not in frame]
        if missing:
            raise ValueError(f"{symbol}: {len(missing)} missing bars on common grid; first={missing[0]}")
        csv_path = csv_dir / f"{symbol[:-4]}_USDT.csv"
        with csv_path.open("x", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(("timestamp", "open", "high", "low", "close", "volume"))
            writer.writerows((timestamp(t), *[frame[t][j] for j in (1, 2, 3, 4, 5)]) for t in grid)
        meta[symbol]["aligned_csv"] = str(csv_path.relative_to(output)).replace("\\", "/")
        meta[symbol]["aligned_csv_sha256"] = digest(csv_path)
    manifest = {"source": "Binance Spot public REST /api/v3/klines", "endpoint": BASE,
                "interval": "8h", "time_zone": "UTC", "retrieved_at_utc": retrieved,
                "common_first_open_utc": timestamp(common_start), "common_last_open_utc": timestamp(common_end),
                "common_bars": len(grid), "no_forward_fill": True, "symbols": meta}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", default="2020-01-01T00:00:00Z")
    parser.add_argument("--end", default="2026-10-01T00:00:00Z", help="exclusive UTC boundary")
    args = parser.parse_args()
    print(json.dumps(collect(args.output, args.start, args.end), indent=2))
