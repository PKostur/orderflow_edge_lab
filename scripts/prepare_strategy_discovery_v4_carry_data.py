from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import time

import pandas as pd
import requests

from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines

SPOT = "https://api.mexc.com/api/v3/klines"
FUNDING = "https://contract.mexc.com/api/v1/contract/funding_rate/history"
HOUR_MS = 60 * 60 * 1000
SPOT_CHUNK_HOURS = 900


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def normalize_hourly(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    out = frame.copy()
    idx = pd.to_datetime(out.index, utc=True)
    out.index = idx.floor("h")
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out


def fetch_spot(symbol: str, start: str, end: str) -> pd.DataFrame:
    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC")
    start_ms = int(start_ts.timestamp() * 1000)
    end_ms = int(end_ts.timestamp() * 1000) - 1
    cursor = start_ms
    rows: list[list] = []
    session = requests.Session()

    while cursor <= end_ms:
        chunk_end = min(end_ms, cursor + SPOT_CHUNK_HOURS * HOUR_MS - 1)
        r = session.get(
            SPOT,
            params={
                "symbol": symbol,
                "interval": "60m",
                "startTime": cursor,
                "endTime": chunk_end,
                "limit": 1000,
            },
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        if not data:
            cursor = chunk_end + 1
            continue

        rows.extend(data)
        returned_times = [int(row[0]) for row in data if row]
        if not returned_times:
            cursor = chunk_end + 1
            continue
        last_open = max(returned_times)
        nxt = max(last_open + HOUR_MS, chunk_end + 1 if last_open < cursor else last_open + HOUR_MS)
        if nxt <= cursor:
            raise RuntimeError(f"spot pagination did not advance for {symbol}: cursor={cursor}, last={last_open}")
        cursor = nxt
        time.sleep(0.04)

    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    parsed = []
    for row in rows:
        if len(row) < 6:
            continue
        parsed.append(row[:6])
    frame = pd.DataFrame(parsed, columns=["open_time", "open", "high", "low", "close", "volume"])
    frame["timestamp"] = pd.to_datetime(pd.to_numeric(frame["open_time"], errors="coerce"), unit="ms", utc=True)
    frame = frame.dropna(subset=["timestamp"]).set_index("timestamp").sort_index()
    for c in ["open", "high", "low", "close", "volume"]:
        frame[c] = pd.to_numeric(frame[c], errors="coerce")
    frame = normalize_hourly(frame[["open", "high", "low", "close", "volume"]].dropna())
    return frame.loc[(frame.index >= start_ts) & (frame.index < end_ts)]


def fetch_funding(symbol: str, start: str, end: str) -> pd.DataFrame:
    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC")
    records: list[dict] = []
    page = 1
    session = requests.Session()
    while page <= 100:
        r = session.get(FUNDING, params={"symbol": symbol, "page_num": page, "page_size": 1000}, timeout=30)
        r.raise_for_status()
        payload = r.json()
        if not payload.get("success"):
            raise RuntimeError(str(payload)[:400])
        data = payload.get("data") or {}
        batch = data.get("resultList") or []
        if not batch:
            break
        records.extend(batch)
        times = [pd.to_datetime(int(x["settleTime"]), unit="ms", utc=True) for x in batch]
        total_page = int(data.get("totalPage") or page)
        if min(times) < start_ts or page >= total_page:
            break
        page += 1
        time.sleep(0.04)
    if not records:
        return pd.DataFrame(columns=["funding_rate"])
    frame = pd.DataFrame(records)
    frame["timestamp"] = pd.to_datetime(pd.to_numeric(frame["settleTime"], errors="coerce"), unit="ms", utc=True)
    frame["funding_rate"] = pd.to_numeric(frame["fundingRate"], errors="coerce")
    frame = frame.dropna(subset=["timestamp", "funding_rate"]).set_index("timestamp").sort_index()
    frame = frame[~frame.index.duplicated(keep="last")]
    return frame.loc[(frame.index >= start_ts) & (frame.index < end_ts), ["funding_rate"]]


def bounds(frame: pd.DataFrame) -> dict[str, str | None]:
    return {
        "first_timestamp": None if frame.empty else str(frame.index.min()),
        "last_timestamp": None if frame.empty else str(frame.index.max()),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--max-workers", type=int, default=3)
    args = ap.parse_args()
    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    start = cfg["data"]["start"]
    end = cfg["data"]["end_exclusive"]
    bases = list(cfg["data"]["candidate_symbols"])
    manifest = {
        "schema_version": 2,
        "protocol_name": cfg["protocol_name"],
        "research_semantics_changed": False,
        "engineering_repairs": [
            "bounded spot-kline pagination",
            "exact-hour timestamp normalization without filling missing observations",
            "per-symbol coverage diagnostics",
        ],
        "start": start,
        "end_exclusive": end,
        "symbols": [],
        "failures": [],
    }

    def load(base: str) -> dict:
        fut_sym = f"{base}_USDT"
        spot_sym = f"{base}USDT"
        futures = normalize_hourly(fetch_mexc_futures_klines(fut_sym, "1h", start, end))
        spot = fetch_spot(spot_sym, start, end)
        funding = fetch_funding(fut_sym, start, end)
        paths = {
            "futures": out / f"{base}_futures_1h.csv",
            "spot": out / f"{base}_spot_1h.csv",
            "funding": out / f"{base}_funding.csv",
        }
        futures.to_csv(paths["futures"])
        spot.to_csv(paths["spot"])
        funding.to_csv(paths["funding"])

        dev_end = pd.Timestamp(cfg["data"]["development_end_exclusive"], tz="UTC")
        dev_start = pd.Timestamp(start, tz="UTC")
        expected = int((dev_end - dev_start).total_seconds() // 3600)
        futures_dev = futures.loc[(futures.index >= dev_start) & (futures.index < dev_end)]
        spot_dev = spot.loc[(spot.index >= dev_start) & (spot.index < dev_end)]
        common = futures_dev.index.intersection(spot_dev.index)
        coverage = len(common) / expected if expected else 0.0
        result = {
            "base": base,
            "expected_development_hours": expected,
            "futures_rows": len(futures),
            "spot_rows": len(spot),
            "funding_rows": len(funding),
            "futures_development_rows": len(futures_dev),
            "spot_development_rows": len(spot_dev),
            "development_common_rows": len(common),
            "development_common_coverage": coverage,
            "admitted_by_data_rule": bool(coverage >= 0.90 and len(funding) > 0),
            "futures_bounds": bounds(futures),
            "spot_bounds": bounds(spot),
            "funding_bounds": bounds(funding),
            "files": {k: {"name": p.name, "sha256": sha256(p)} for k, p in paths.items()},
        }
        print(json.dumps({
            "base": base,
            "coverage": round(coverage, 6),
            "futures_dev": len(futures_dev),
            "spot_dev": len(spot_dev),
            "common_dev": len(common),
            "funding_rows": len(funding),
            "admitted": result["admitted_by_data_rule"],
            "futures_bounds": result["futures_bounds"],
            "spot_bounds": result["spot_bounds"],
            "funding_bounds": result["funding_bounds"],
        }, sort_keys=True), flush=True)
        return result

    with ThreadPoolExecutor(max_workers=max(1, min(args.max_workers, len(bases)))) as pool:
        jobs = {pool.submit(load, base): base for base in bases}
        for job in as_completed(jobs):
            base = jobs[job]
            try:
                manifest["symbols"].append(job.result())
            except Exception as exc:
                failure = {"base": base, "type": type(exc).__name__, "message": str(exc)[:500]}
                manifest["failures"].append(failure)
                print(json.dumps({"failure": failure}, sort_keys=True), flush=True)

    manifest["symbols"].sort(key=lambda x: x["base"])
    manifest["failures"].sort(key=lambda x: x["base"])
    admitted = [x["base"] for x in manifest["symbols"] if x["admitted_by_data_rule"]]
    manifest["admitted_symbols"] = admitted
    manifest["admitted_count"] = len(admitted)
    manifest_path = out / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"admitted": admitted, "failures": manifest["failures"], "manifest": str(manifest_path)}, indent=2), flush=True)
    if len(admitted) < 4:
        raise SystemExit("fewer than four carry symbols satisfy frozen data coverage rule")


if __name__ == "__main__":
    main()
