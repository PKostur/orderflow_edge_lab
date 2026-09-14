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


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch_spot(symbol: str, start: str, end: str) -> pd.DataFrame:
    start_ms = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
    end_ms = int(pd.Timestamp(end, tz="UTC").timestamp() * 1000) - 1
    cursor = start_ms
    rows: list[list] = []
    session = requests.Session()
    while cursor <= end_ms:
        r = session.get(
            SPOT,
            params={"symbol": symbol, "interval": "60m", "startTime": cursor, "endTime": end_ms, "limit": 1000},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        if not data:
            break
        rows.extend(data)
        nxt = int(data[-1][0]) + 60 * 60 * 1000
        if nxt <= cursor:
            break
        cursor = nxt
        if len(data) < 1000:
            break
        time.sleep(0.05)
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    frame = pd.DataFrame(rows, columns=["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume"])
    frame["timestamp"] = pd.to_datetime(frame["open_time"], unit="ms", utc=True)
    frame = frame.set_index("timestamp").sort_index()
    for c in ["open", "high", "low", "close", "volume"]:
        frame[c] = pd.to_numeric(frame[c], errors="coerce")
    frame = frame.loc[(frame.index >= pd.Timestamp(start, tz="UTC")) & (frame.index < pd.Timestamp(end, tz="UTC"))]
    return frame[["open", "high", "low", "close", "volume"]].dropna()


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
        if min(times) < start_ts or page >= int(data.get("totalPage") or page):
            break
        page += 1
        time.sleep(0.05)
    if not records:
        return pd.DataFrame(columns=["funding_rate"])
    frame = pd.DataFrame(records)
    frame["timestamp"] = pd.to_datetime(frame["settleTime"].astype("int64"), unit="ms", utc=True)
    frame["funding_rate"] = pd.to_numeric(frame["fundingRate"], errors="coerce")
    frame = frame.set_index("timestamp").sort_index()
    return frame.loc[(frame.index >= start_ts) & (frame.index < end_ts), ["funding_rate"]].dropna()


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
    manifest = {"schema_version": 1, "protocol_name": cfg["protocol_name"], "start": start, "end_exclusive": end, "symbols": [], "failures": []}

    def load(base: str) -> dict:
        fut_sym = f"{base}_USDT"
        spot_sym = f"{base}USDT"
        futures = fetch_mexc_futures_klines(fut_sym, "1h", start, end)
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
        expected = int((dev_end - dev_start) / pd.Timedelta(hours=1))
        common = futures.index.intersection(spot.index)
        common_dev = common[(common >= dev_start) & (common < dev_end)]
        coverage = len(common_dev) / expected if expected else 0.0
        return {
            "base": base,
            "futures_rows": len(futures),
            "spot_rows": len(spot),
            "funding_rows": len(funding),
            "development_common_coverage": coverage,
            "admitted_by_data_rule": bool(coverage >= 0.90 and len(funding) > 0),
            "files": {k: {"name": p.name, "sha256": sha256(p)} for k, p in paths.items()},
        }

    with ThreadPoolExecutor(max_workers=max(1, min(args.max_workers, len(bases)))) as pool:
        jobs = {pool.submit(load, base): base for base in bases}
        for job in as_completed(jobs):
            base = jobs[job]
            try:
                manifest["symbols"].append(job.result())
            except Exception as exc:
                manifest["failures"].append({"base": base, "type": type(exc).__name__, "message": str(exc)[:500]})
    manifest["symbols"].sort(key=lambda x: x["base"])
    manifest["failures"].sort(key=lambda x: x["base"])
    admitted = [x["base"] for x in manifest["symbols"] if x["admitted_by_data_rule"]]
    manifest["admitted_symbols"] = admitted
    manifest["admitted_count"] = len(admitted)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"admitted": admitted, "failures": manifest["failures"]}, indent=2))
    if len(admitted) < 4:
        raise SystemExit("fewer than four carry symbols satisfy frozen data coverage rule")


if __name__ == "__main__":
    main()
