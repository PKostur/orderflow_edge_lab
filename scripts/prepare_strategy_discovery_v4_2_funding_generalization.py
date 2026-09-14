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

BASE = "https://api.mexc.com"
SPOT_INFO = f"{BASE}/api/v3/exchangeInfo"
SPOT_TICKER = f"{BASE}/api/v3/ticker/24hr"
SPOT_KLINES = f"{BASE}/api/v3/klines"
FUTURES_DETAIL = f"{BASE}/api/v1/contract/detail"
FUNDING = f"{BASE}/api/v1/contract/funding_rate/history"
HOUR_MS = 3_600_000
SPOT_CHUNK_HOURS = 900


def _get_json(session: requests.Session, url: str, *, params: dict | None = None, tries: int = 5):
    last = None
    for attempt in range(tries):
        try:
            r = session.get(url, params=params, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as exc:  # transport-only retry
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"request failed after {tries} attempts: {url}: {last}")


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
    out.index = pd.to_datetime(out.index, utc=True).floor("h")
    return out[~out.index.duplicated(keep="last")].sort_index()


def fetch_spot(symbol: str, start: str, end: str) -> pd.DataFrame:
    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC")
    cursor = int(start_ts.timestamp() * 1000)
    end_ms = int(end_ts.timestamp() * 1000) - 1
    rows: list[list] = []
    session = requests.Session()
    while cursor <= end_ms:
        chunk_end = min(end_ms, cursor + SPOT_CHUNK_HOURS * HOUR_MS - 1)
        data = _get_json(session, SPOT_KLINES, params={
            "symbol": symbol, "interval": "60m", "startTime": cursor,
            "endTime": chunk_end, "limit": 1000,
        })
        if isinstance(data, dict) and "data" in data:
            data = data["data"]
        if not data:
            cursor = chunk_end + 1
            continue
        rows.extend(data)
        times = [int(row[0]) for row in data if row]
        last_open = max(times) if times else cursor
        nxt = last_open + HOUR_MS
        cursor = nxt if nxt > cursor else chunk_end + 1
        time.sleep(0.06)
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    parsed = [row[:6] for row in rows if len(row) >= 6]
    frame = pd.DataFrame(parsed, columns=["open_time", "open", "high", "low", "close", "volume"])
    frame["timestamp"] = pd.to_datetime(pd.to_numeric(frame.open_time, errors="coerce"), unit="ms", utc=True)
    frame = frame.dropna(subset=["timestamp"]).set_index("timestamp").sort_index()
    for c in ["open", "high", "low", "close", "volume"]:
        frame[c] = pd.to_numeric(frame[c], errors="coerce")
    frame = normalize_hourly(frame[["open", "high", "low", "close", "volume"]].dropna())
    return frame.loc[(frame.index >= start_ts) & (frame.index < end_ts)]


def fetch_funding(symbol: str, start: str, end: str) -> pd.DataFrame:
    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC")
    session = requests.Session()
    records: list[dict] = []
    page = 1
    while page <= 100:
        payload = _get_json(session, FUNDING, params={"symbol": symbol, "page_num": page, "page_size": 1000})
        if not isinstance(payload, dict) or payload.get("success") is not True:
            raise RuntimeError(f"funding response failed for {symbol}: {str(payload)[:400]}")
        data = payload.get("data") or {}
        batch = data.get("resultList") or []
        if not batch:
            break
        records.extend(batch)
        times = [pd.to_datetime(int(x["settleTime"]), unit="ms", utc=True) for x in batch if x.get("settleTime")]
        total_page = int(data.get("totalPage") or page)
        if not times or min(times) < start_ts or page >= total_page:
            break
        page += 1
        time.sleep(0.08)
    if not records:
        return pd.DataFrame(columns=["funding_rate"])
    frame = pd.DataFrame(records)
    frame["timestamp"] = pd.to_datetime(pd.to_numeric(frame["settleTime"], errors="coerce"), unit="ms", utc=True)
    frame["funding_rate"] = pd.to_numeric(frame["fundingRate"], errors="coerce")
    frame = frame.dropna(subset=["timestamp", "funding_rate"]).set_index("timestamp").sort_index()
    frame = frame[~frame.index.duplicated(keep="last")]
    return frame.loc[(frame.index >= start_ts) & (frame.index < end_ts), ["funding_rate"]]


def current_candidate_snapshot(cfg: dict) -> dict:
    session = requests.Session()
    spot_info = _get_json(session, SPOT_INFO)
    tickers = _get_json(session, SPOT_TICKER)
    fut = _get_json(session, FUTURES_DETAIL)

    spot_rows = spot_info.get("symbols", []) if isinstance(spot_info, dict) else []
    spot_by_base: dict[str, str] = {}
    for row in spot_rows:
        sym = str(row.get("symbol", "")).upper()
        base = str(row.get("baseAsset", "")).upper()
        quote = str(row.get("quoteAsset", "")).upper()
        if quote == "USDT" and sym.endswith("USDT") and base:
            spot_by_base[base] = sym

    qvol: dict[str, float] = {}
    ticker_rows = tickers if isinstance(tickers, list) else tickers.get("data", []) if isinstance(tickers, dict) else []
    for row in ticker_rows:
        sym = str(row.get("symbol", "")).upper()
        try:
            qvol[sym] = float(row.get("quoteVolume") or 0.0)
        except (TypeError, ValueError):
            qvol[sym] = 0.0

    frows = fut.get("data", []) if isinstance(fut, dict) else []
    futures_by_base: dict[str, str] = {}
    for row in frows:
        sym = str(row.get("symbol", "")).upper()
        quote = str(row.get("quoteCoin", "USDT")).upper()
        if not sym.endswith("_USDT") or quote != "USDT":
            continue
        base = str(row.get("baseCoin", "")).upper() or sym[:-5]
        if base:
            futures_by_base[base] = sym

    original = set(cfg["source_observation"]["original_symbols"])
    excluded = set(cfg["universe_construction"]["exclude_stablecoin_like_bases"])
    shared = sorted(set(spot_by_base).intersection(futures_by_base))
    candidates = [b for b in shared if b not in original and b not in excluded]
    candidates.sort(key=lambda b: (-qvol.get(spot_by_base[b], 0.0), b))
    cap = int(cfg["universe_construction"]["maximum_historical_fetch_candidates"])
    chosen = candidates[:cap]
    return {
        "spot_symbol_count": len(spot_by_base),
        "futures_symbol_count": len(futures_by_base),
        "intersection_count": len(shared),
        "eligible_expansion_count": len(candidates),
        "ranked_expansion_candidates": [
            {"base": b, "spot_symbol": spot_by_base[b], "futures_symbol": futures_by_base[b],
             "snapshot_spot_quote_volume": qvol.get(spot_by_base[b], 0.0)} for b in chosen
        ],
        "spot_by_base": spot_by_base,
        "futures_by_base": futures_by_base,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--max-workers", type=int, default=3)
    args = ap.parse_args()
    cfg = json.loads(Path(args.config).read_text())
    out = Path(args.output_dir); out.mkdir(parents=True, exist_ok=True)
    snap = current_candidate_snapshot(cfg)
    (out / "universe_snapshot.json").write_text(json.dumps(snap, indent=2, sort_keys=True))

    start = cfg["data"]["development_start"]
    end = cfg["data"]["development_end_exclusive"]
    start_ts = pd.Timestamp(start, tz="UTC"); end_ts = pd.Timestamp(end, tz="UTC")
    expected = int((end_ts - start_ts).total_seconds() // 3600)
    original = list(cfg["source_observation"]["original_symbols"])
    ranked = [x["base"] for x in snap["ranked_expansion_candidates"]]
    fetch_bases = list(dict.fromkeys(["BTC"] + original + ranked))
    spot_by_base = snap["spot_by_base"]
    futures_by_base = snap["futures_by_base"]
    manifest = {"schema_version":1,"protocol":cfg["protocol_name"],"start":start,"end_exclusive":end,
                "snapshot_sha256":sha256(out/"universe_snapshot.json"),"symbols":[],"failures":[]}

    def load(base: str) -> dict:
        if base not in spot_by_base or base not in futures_by_base:
            raise RuntimeError(f"current spot/perp intersection missing for {base}")
        futsym = futures_by_base[base]; spotsym = spot_by_base[base]
        futures = normalize_hourly(fetch_mexc_futures_klines(futsym, "1h", start, end, rest_base=BASE, request_pause_seconds=0.35))
        spot = fetch_spot(spotsym, start, end)
        funding = fetch_funding(futsym, start, end)
        fp=out/f"{base}_futures_1h.csv"; sp=out/f"{base}_spot_1h.csv"; frp=out/f"{base}_funding.csv"
        futures.to_csv(fp); spot.to_csv(sp); funding.to_csv(frp)
        common = futures.index.intersection(spot.index)
        coverage = len(common) / expected if expected else 0.0
        spot_notional = (spot.close.astype(float) * spot.volume.astype(float)).replace([float("inf"), -float("inf")], pd.NA).dropna()
        median_notional = float(spot_notional.median()) if len(spot_notional) else 0.0
        hist = cfg["universe_construction"]["historical_admission"]
        expansion = base in ranked
        admitted = bool(expansion and coverage >= float(hist["minimum_common_spot_perp_hour_coverage"])
                        and len(funding) >= int(hist["minimum_funding_rows"])
                        and median_notional >= float(hist["minimum_median_spot_hourly_notional_usdt"]))
        reasons=[]
        if expansion:
            if coverage < float(hist["minimum_common_spot_perp_hour_coverage"]): reasons.append("coverage")
            if len(funding) < int(hist["minimum_funding_rows"]): reasons.append("funding_rows")
            if median_notional < float(hist["minimum_median_spot_hourly_notional_usdt"]): reasons.append("spot_notional")
        return {"base":base,"expansion_candidate":expansion,"coverage":coverage,"funding_rows":len(funding),
                "median_spot_hourly_notional_usdt":median_notional,"admitted_expansion":admitted,
                "rejection_reasons":reasons,"futures_rows":len(futures),"spot_rows":len(spot),
                "files":{"futures":{"name":fp.name,"sha256":sha256(fp)},"spot":{"name":sp.name,"sha256":sha256(sp)},"funding":{"name":frp.name,"sha256":sha256(frp)}}}

    with ThreadPoolExecutor(max_workers=max(1,min(args.max_workers,len(fetch_bases)))) as pool:
        jobs={pool.submit(load,b):b for b in fetch_bases}
        for job in as_completed(jobs):
            b=jobs[job]
            try: manifest["symbols"].append(job.result())
            except Exception as exc: manifest["failures"].append({"base":b,"type":type(exc).__name__,"message":str(exc)[:500]})

    manifest["symbols"].sort(key=lambda x:x["base"]); manifest["failures"].sort(key=lambda x:x["base"])
    admitted=[x for x in manifest["symbols"] if x["admitted_expansion"]]
    admitted.sort(key=lambda x:(-x["median_spot_hourly_notional_usdt"],x["base"]))
    size=int(cfg["universe_construction"]["primary_panel_size"])
    manifest["primary_expansion_panel"]=[x["base"] for x in admitted[:size]]
    manifest["admitted_expansion_count_before_cap"]=len(admitted)
    manifest["original_symbols_available_for_diagnostic"]=[b for b in original if any(x["base"]==b and x["futures_rows"]>0 for x in manifest["symbols"])]
    mp=out/"manifest.json"; mp.write_text(json.dumps(manifest,indent=2,sort_keys=True))
    print(json.dumps({"primary_expansion_panel":manifest["primary_expansion_panel"],"admitted_before_cap":len(admitted),"failures":manifest["failures"]},indent=2))
    if len(manifest["primary_expansion_panel"]) < int(cfg["universe_construction"]["minimum_primary_panel_size"]):
        raise SystemExit("v4.2 primary expansion panel is below frozen minimum size")
    if "BTC" not in [x["base"] for x in manifest["symbols"]]:
        raise SystemExit("BTC hedge/context data missing")


if __name__ == "__main__":
    main()
