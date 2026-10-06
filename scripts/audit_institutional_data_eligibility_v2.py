from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def fetch_json(url: str, timeout: float = 20.0) -> dict[str, Any]:
    req = Request(url, headers={"Accept": "application/json", "User-Agent": "orderflow-edge-lab/1.0"})
    with urlopen(req, timeout=timeout) as response:
        raw = response.read(8_000_000)
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("expected JSON object")
    return payload


def ok_payload(payload: dict[str, Any]) -> bool:
    return payload.get("success") is True and payload.get("data") is not None


def probe(base: str, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    url = base.rstrip("/") + "/api/v1/" + path.lstrip("/")
    if params:
        url += "?" + urlencode(params)
    try:
        payload = fetch_json(url)
        data = payload.get("data")
        if isinstance(data, dict):
            fields = sorted(data.keys())
            size = len(data)
        elif isinstance(data, list):
            fields = sorted(data[0].keys()) if data and isinstance(data[0], dict) else []
            size = len(data)
        else:
            fields = []
            size = 0
        return {"url_path": path, "ok": ok_payload(payload), "fields": fields, "size": size, "error": None}
    except Exception as exc:  # audit must record failure, not invent availability
        return {"url_path": path, "ok": False, "fields": [], "size": 0, "error": f"{type(exc).__name__}: {exc}"}


def classify(probes: dict[str, dict[str, Any]]) -> dict[str, str]:
    depth_live = probes["depth"]["ok"]
    deals_live = probes["deals"]["ok"]
    funding_history = probes["funding_history"]["ok"]
    index_history = probes["index_kline"]["ok"]
    fair_history = probes["fair_kline"]["ok"]
    ohlcv_history = probes["kline"]["ok"]

    # The frozen approved public endpoint set contains no historical OI endpoint.
    historical_oi = False

    return {
        "microprice_imbalance_continuation": "prospective_capture_only" if depth_live else "blocked_missing_field",
        "depth_pull_absorption_reversal": "prospective_capture_only" if depth_live and deals_live else "blocked_missing_field",
        "cvd_price_divergence": "prospective_capture_only" if deals_live else "blocked_missing_field",
        "large_trade_flow_acceleration": "prospective_capture_only" if deals_live else "blocked_missing_field",
        "funding_oi_crowding_reversal": "historical_ready" if funding_history and historical_oi else "blocked_missing_field",
        "basis_convergence": "historical_ready" if index_history and fair_history else "blocked_missing_field",
        "btc_lead_lag_residual_momentum": "historical_ready" if ohlcv_history else "blocked_missing_field",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/unrelated_strategy_tournament_v2_2_data_eligibility.json")
    parser.add_argument("--out", default="research/unrelated_strategy_tournament_v2_2_data_eligibility")
    args = parser.parse_args()

    cfg = json.load(open(args.config, encoding="utf-8"))
    assert cfg["outcomes_inspected_before_freeze"] is False
    assert cfg["claims"]["strategy_pnl_permitted"] is False

    base = cfg["sources"]["mexc_public_rest"]["base"]
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    per_symbol: dict[str, Any] = {}
    now = int(time.time())
    start = now - 30 * 24 * 3600

    for symbol in cfg["audit_symbols"]:
        probes = {
            "depth": probe(base, f"contract/depth/{symbol}"),
            "deals": probe(base, f"contract/deals/{symbol}", {"limit": 100}),
            "funding_history": probe(base, "contract/funding_rate/history", {"symbol": symbol, "page_num": 1, "page_size": 100}),
            "ticker": probe(base, "contract/ticker", {"symbol": symbol}),
            "kline": probe(base, f"contract/kline/{symbol}", {"interval": "Min60", "start": start, "end": now}),
            "index_kline": probe(base, f"contract/kline/index_price/{symbol}", {"interval": "Min60", "start": start, "end": now}),
            "fair_kline": probe(base, f"contract/kline/fair_price/{symbol}", {"interval": "Min60", "start": start, "end": now}),
        }
        per_symbol[symbol] = {"probes": probes, "family_classification": classify(probes)}
        time.sleep(0.5)

    families = list(cfg["families"].keys())
    aggregate: dict[str, Any] = {}
    rank = {"historical_ready": 0, "prospective_capture_only": 1, "needs_existing_entitlement_check": 2, "blocked_missing_field": 3}
    for family in families:
        statuses = [per_symbol[s]["family_classification"][family] for s in cfg["audit_symbols"]]
        aggregate[family] = {
            "per_symbol": dict(zip(cfg["audit_symbols"], statuses)),
            "overall": max(statuses, key=lambda x: rank[x]),
        }

    summary = {
        "protocol": cfg["protocol_name"],
        "audit_symbols": cfg["audit_symbols"],
        "families": aggregate,
        "historical_open_interest_explicitly_observed": False,
        "note": "No strategy PnL or signal ranking was performed. Live depth/deals eligibility means prospective capture only, not historical backtest readiness.",
        "claims": cfg["claims"],
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (out_dir / "probes.json").write_text(json.dumps(per_symbol, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
