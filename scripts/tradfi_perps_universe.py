"""Build ``research/tradfi_perps_forward/universe_v1.json`` for ``tradfi-perps-forward-v1``.

Inputs: the committed exchangeInfo snapshot (metadata only) and Yahoo quote METADATA (quoteType, exchange, longName from the
search endpoint; no prices).  Mapping and exclusion rules come from ``config/tradfi_perps_forward_v1.json``:

* in scope: contractType TRADIFI_PERPETUAL, quoteAsset USDT, status TRADING, underlyingType EQUITY or COMMODITY;
* Yahoo symbol = baseAsset (BRKB -> BRK-B); commodities by the futures map;
* stock books: Yahoo quoteType EQUITY only (ETFs, including leveraged and inverse ETFs, and unmapped symbols are excluded).

The snapshot carries two ``SPCX`` base assets (SPCXUSDT and SPCXUSD1): rows are keyed by perp symbol and the USD1 quote is
excluded by the quote-asset rule.  Run once before the start; the output is frozen with the watch.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request

from orderflow_edge_lab.tradfi_perps_forward import COMMODITY_MAP, SYMBOL_OVERRIDES, WATCH_ID, yahoo_symbol

SNAPSHOT = "research/tradfi_perps_forward/exchangeInfo_2026-10-13.json"
CONFIG = "config/tradfi_perps_forward_v1.json"
OUTPUT = "research/tradfi_perps_forward/universe_v1.json"
SEARCH = "https://query1.finance.yahoo.com/v1/finance/search?q={q}&quotesCount=10&newsCount=0&listsCount=0"
EXCLUDED_UNDERLYING = {"HK_EQUITY", "KR_EQUITY", "CN_EQUITY", "PREMARKET", "FX"}


def _search(query: str, retries: int) -> list[dict]:
    url = SEARCH.format(q=urllib.parse.quote(query, safe=""))
    last: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response).get("quotes", [])
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last = exc
            time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"yahoo search failed for {query}: {last}")


def yahoo_metadata(symbol: str, retries: int = 3) -> dict | None:
    """quoteType / exchange / longName of the EXACT symbol match in Yahoo's search results.

    None: Yahoo has no exact match.  ``{"unavailable": ...}``: the search endpoint kept answering HTTP 500 for this ticker
    (it does so for a few bare tickers, e.g. XLE); the symbol is then excluded as unmapped (conservative: never in the
    stock books on missing metadata).  The prices-carrying lookup endpoint is deliberately not used."""
    try:
        quotes = _search(symbol, retries)
    except RuntimeError as exc:
        return {"unavailable": str(exc)}
    for q in quotes:
        if str(q.get("symbol", "")).upper() == symbol.upper():
            return {"quote_type": q.get("quoteType"), "exchange": q.get("exchange"),
                    "long_name": q.get("longname") or q.get("shortname")}
    return None


def classify(row: dict, meta: dict | None) -> dict:
    """Universe row for one perp: group (stock | etf | commodity | excluded), stock-book flag and exclusion reason."""
    base = row["baseAsset"]
    ysym = yahoo_symbol(base, row["underlyingType"])
    entry = {
        "symbol": row["symbol"], "base_asset": base, "underlying_type": row["underlyingType"],
        "quote_asset": row["quoteAsset"], "status": row["status"],
        "onboard_date": datetime.fromtimestamp(row["onboardDate"] / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "yahoo_symbol": ysym, "quote_type": None, "exchange": None, "long_name": None,
        "group": "excluded", "stock_book": False, "exclusion_reason": None,
    }
    if meta and "unavailable" not in meta:
        entry.update(quote_type=meta["quote_type"], exchange=meta["exchange"], long_name=meta["long_name"])
    if row["underlyingType"] in EXCLUDED_UNDERLYING:
        entry["exclusion_reason"] = f"underlyingType {row['underlyingType']} is outside the registered universe"
    elif row["underlyingType"] not in ("EQUITY", "COMMODITY"):
        entry["exclusion_reason"] = f"underlyingType {row['underlyingType']} is not EQUITY or COMMODITY"
    elif row["quoteAsset"] != "USDT":
        entry["exclusion_reason"] = f"quoteAsset {row['quoteAsset']} is not USDT (duplicate base asset {base})"
    elif row["status"] != "TRADING":
        entry["exclusion_reason"] = f"status {row['status']} is not TRADING"
    elif ysym is None:
        entry["exclusion_reason"] = "unmapped: no Yahoo symbol in the registered mapping"
    elif row["underlyingType"] == "COMMODITY":
        entry["group"] = "commodity"
        entry["exclusion_reason"] = "commodity: carried for funding diagnostics only, not in the stock books"
    elif meta is None:
        entry["exclusion_reason"] = f"unmapped: Yahoo has no exact match for {ysym}"
    elif "unavailable" in meta:
        entry["exclusion_reason"] = f"unmapped: Yahoo metadata unavailable for {ysym} (search endpoint error)"
    elif meta["quote_type"] == "EQUITY":
        entry["group"], entry["stock_book"] = "stock", True
    elif meta["quote_type"] == "ETF":
        entry["group"] = "etf"
        entry["exclusion_reason"] = "ETF (quoteType ETF): excluded from the stock books"
    else:
        entry["exclusion_reason"] = f"quoteType {meta['quote_type']} is not EQUITY: excluded from the stock books"
    return entry


def build(snapshot_path: str = SNAPSHOT, workers: int = 4) -> dict:
    raw = Path(snapshot_path).read_bytes()
    rows = [r for r in json.loads(raw)["symbols"] if r["contractType"] == "TRADIFI_PERPETUAL"]
    need = {r["symbol"]: yahoo_symbol(r["baseAsset"], r["underlyingType"]) for r in rows
            if r["underlyingType"] == "EQUITY" and r["quoteAsset"] == "USDT" and r["status"] == "TRADING"}
    ysyms = sorted({v for v in need.values() if v})
    with ThreadPoolExecutor(max_workers=workers) as pool:
        meta = dict(zip(ysyms, pool.map(yahoo_metadata, ysyms)))
    entries = [classify(r, meta.get(need.get(r["symbol"], ""))) for r in sorted(rows, key=lambda r: r["symbol"])]
    counts = {g: sum(1 for e in entries if e["group"] == g) for g in ("stock", "etf", "commodity", "excluded")}
    counts["stock_book"] = sum(1 for e in entries if e["stock_book"])
    counts["unmapped"] = sum(1 for e in entries if (e["exclusion_reason"] or "").startswith("unmapped"))
    counts["tradfi_perps_in_snapshot"] = len(entries)
    dup = sorted(b for b in {e["base_asset"] for e in entries} if sum(e["base_asset"] == b for e in entries) > 1)
    return {
        "schema_version": 1, "watch_id": WATCH_ID,
        "built_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "inputs": {"exchange_info_snapshot": snapshot_path, "exchange_info_sha256": sha256(raw).hexdigest(),
                   "config": CONFIG, "config_sha256": sha256(Path(CONFIG).read_bytes()).hexdigest(),
                   "yahoo": "search endpoint metadata only (quoteType, exchange, longName); no prices"},
        "mapping": {"commodities": COMMODITY_MAP, "overrides": SYMBOL_OVERRIDES},
        "duplicate_base_assets": dup, "duplicate_handling": "rows keyed by perp symbol; non-USDT quotes excluded",
        "counts": counts, "symbols": entries,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", default=SNAPSHOT)
    parser.add_argument("--output", default=OUTPUT)
    args = parser.parse_args(argv)
    universe = build(args.snapshot)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(universe, indent=1, sort_keys=False) + "\n", encoding="utf-8")
    print(json.dumps(universe["counts"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
