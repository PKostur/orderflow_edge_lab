"""One-shot evaluation of ``universal-pre-window-crypto-holdout-v1``.

Runs the frozen DON8/EMA8/VOL8 v3 portfolio on MEXC data from before the
development window.  The primary hypothesis and its pass rule come from the
config; nothing here can change them.
"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from orderflow_edge_lab.trend_portfolio_forward import _utc, sleeve_daily_returns, summarize

PROTOCOL_ID = "universal-pre-window-crypto-holdout-v1"
PROTOCOL_IDS = (PROTOCOL_ID, "universal-untouched-coins-holdout-v1")


class HoldoutError(ValueError):
    pass


def clip_to_window(frames: Mapping[str, pd.DataFrame], window: Mapping[str, str]) -> dict[str, pd.DataFrame]:
    start, end = _utc(window["start"]), _utc(window["end_exclusive"])
    out = {}
    for s, f in frames.items():
        f = f.copy()
        f.index = pd.to_datetime(f.index, utc=True)
        f = f.loc[(f.index >= start) & (f.index < end)]
        # Default guard is the development-window start (frozen v1 behaviour); a protocol
        # whose data was never used anywhere may disable it with an explicit null.
        guard = window["must_end_before"] if "must_end_before" in window else "2024-01-01T00:00:00Z"
        if guard and len(f) and f.index.max() >= _utc(guard):
            raise HoldoutError(f"{s}: data overlaps the development window")
        out[s] = f
    return out


def evaluate(config: Mapping[str, Any], frames: Mapping[str, pd.DataFrame]) -> dict[str, Any]:
    if config.get("protocol_id") not in PROTOCOL_IDS:
        raise HoldoutError("wrong protocol config")
    clipped = clip_to_window(frames, config["window"])
    symbols = [s for s in config["source"]["symbols"] if len(clipped.get(s, [])) > 200]
    base = {**config, "source": {**config["source"], "symbols": symbols}}
    sleeves = sleeve_daily_returns(base, clipped)
    lags = int(config["hypotheses"]["primary"].get("newey_west_lags", 5)) if "newey_west_lags" in config["hypotheses"]["primary"] else 5
    combined = sleeves.mean(axis=1)
    primary = summarize(combined, nw_lags=lags)
    passed = bool(
        primary["mean_daily_bps"] is not None
        and primary["mean_daily_bps"] > 0
        and primary["newey_west_t"] is not None
        and primary["newey_west_t"] >= 2.0
    )
    per_strategy = {
        spec["audit_id"]: summarize(
            sleeves[[c for c in sleeves if c.startswith(spec["audit_id"] + ":")]].mean(axis=1), nw_lags=lags
        )
        for spec in config["strategies"]
    }
    per_year = {}
    for year, r in combined.groupby(combined.index.year):
        per_year[str(year)] = {"return": float((1 + r).prod() - 1), "days": int(len(r))}
    inv = sleeve_daily_returns(
        {**base, "sizing": {"method": "entry_inverse_vol", "window_bars": 180, "target_annual_vol": 0.15, "cap": 1.0}},
        clipped,
    ).mean(axis=1)
    data_hash = sha256(
        "".join(
            f"{s}:{len(clipped[s])}:{float(clipped[s]['open'].sum()):.6f}" for s in sorted(clipped)
        ).encode()
    ).hexdigest()
    return {
        "schema_version": 1,
        "protocol_id": str(config["protocol_id"]),
        "window": dict(config["window"]),
        "symbols_evaluated": symbols,
        "bars_per_symbol": {s: int(len(clipped[s])) for s in sorted(clipped)},
        "data_hash": data_hash,
        "primary": {**primary, "pass_rule": config["hypotheses"]["primary"]["pass_rule"], "passed": passed},
        "secondary": {
            "per_strategy": per_strategy,
            "per_year": per_year,
            "inverse_vol_sizing": summarize(inv, nw_lags=lags),
        },
        "known_bias": config["economics"]["funding"],
        "claims": dict(config["claims"]),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines

    parser = argparse.ArgumentParser(description="Evaluate the pre-window crypto holdout once.")
    parser.add_argument("--config", default="config/universal_pre_window_crypto_holdout_v1.json")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    w = config["window"]
    frames = {s: fetch_mexc_futures_klines(s, config["source"]["interval"], w["start"], w["end_exclusive"])
              for s in config["source"]["symbols"]}
    report = evaluate(config, frames)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["primary"]["passed"], "t": report["primary"]["newey_west_t"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
