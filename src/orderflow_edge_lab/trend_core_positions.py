"""Position sheet for a person who holds the crypto trend core by hand (config/crypto_trend_core_v1.json).

For every coin it gives the net position the frozen DON8 + EMA8 sleeves hold after the latest completed 8h bar:
each sleeve's inverse-vol target (exactly what canonical v3 enters at the next bar's open), summed over the two
strategies and divided by the 34 sleeves, so the weights are a fraction of account equity at 1x.  A leverage factor
scales every weight.  Under canonical v3 a sleeve keeps its quantity until its own signal changes, so a coin needs
trading only when one of its sleeves changed.

Descriptive output for manual use; it sends no orders and holds no keys.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from orderflow_edge_lab.trend_portfolio_forward import _utc, completed_bars
from orderflow_edge_lab.universal_backtest import legacy_strategy
from orderflow_edge_lab.vol_sizing import vol_sized_strategy

BAR = pd.Timedelta(hours=8)


def sleeve_targets(config: Mapping[str, Any], frames: Mapping[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Per coin: one column per strategy, the signed sleeve target stamped at each completed bar's open label."""
    s = config["sizing"]
    out = {}
    for coin, frame in frames.items():
        cols = {}
        for spec in config["strategies"]:
            strat = vol_sized_strategy(legacy_strategy(str(spec["family"])), window=int(s["window_bars"]),
                                       target_vol=float(s["target_annual_vol"]), cap=float(s["cap"]),
                                       bars_per_year=int(s.get("bars_per_year", 1095)))
            t = strat.generate_target(frame, dict(spec["parameters"]), None).reindex(frame.index).fillna(0.0)
            cols[str(spec["audit_id"])] = t.clip(-float(config["economics"]["max_abs_position"]),
                                                 float(config["economics"]["max_abs_position"]))
        out[coin] = pd.DataFrame(cols)
    return out


def _since(col: pd.Series) -> str | None:
    """Close time of the bar where the sleeve's current value started (None when flat)."""
    v = col.iloc[-1]
    if v == 0:
        return None
    start = col.index[-1]
    for ts, x in col.iloc[::-1].items():
        if x != v:
            break
        start = ts
    return (start + BAR).isoformat()


def build_sheet(config: Mapping[str, Any], frames: Mapping[str, pd.DataFrame], *, as_of: Any, leverage: float,
                equity: float, lookback_bars: int = 3) -> dict[str, Any]:
    """Rows per coin plus totals.  ``lookback_bars`` sets how far back "changed" looks (3 bars = the last 24h)."""
    as_of_ts = _utc(as_of)
    coins = [c for m in config["groups"].values() for c in m]
    missing = [c for c in coins if c not in frames]
    if missing:
        raise ValueError(f"missing frames: {missing}")
    clean = {c: completed_bars(frames[c], as_of_ts) for c in coins}
    targets = sleeve_targets(config, clean)
    n_sleeves = len(coins) * len(config["strategies"])
    last_bars = {c: t.index[-1] for c, t in targets.items() if len(t)}
    signal_bar = max(last_bars.values())
    stale = sorted(c for c, ts in last_bars.items() if ts < signal_bar)
    rows = []
    for c in coins:
        t = targets[c]
        now = t.iloc[-1]
        before = t.iloc[-1 - lookback_bars] if len(t) > lookback_bars else t.iloc[0] * 0.0
        changed = [k for k in t.columns if now[k] != before[k]]
        w = float(now.sum()) / n_sleeves
        w_before = float(before.sum()) / n_sleeves
        price = float(clean[c]["close"].iloc[-1])
        notional = w * leverage * equity
        if not changed:
            action = "HOLD"
        elif w == 0:
            action = "CLOSE"
        elif w_before == 0:
            action = "OPEN"
        elif (w > 0) != (w_before > 0):
            action = "FLIP"
        else:
            action = "RESIZE"
        rows.append({
            "coin": c, "action": action, "side": "LONG" if w > 0 else ("SHORT" if w < 0 else "FLAT"),
            "weight_1x": w, "weight_levered": w * leverage, "notional_usdt": notional,
            "quantity": notional / price if price > 0 else None, "reference_price": price,
            "previous_weight_1x": w_before, "changed_sleeves": changed,
            "sleeves": {k: float(now[k]) for k in t.columns},
            "sleeve_since_utc": {k: _since(t[k]) for k in t.columns},
            "last_bar_close_utc": (t.index[-1] + BAR).isoformat(),
        })
    gross = sum(abs(r["weight_levered"]) for r in rows)
    net = sum(r["weight_levered"] for r in rows)
    return {
        "schema_version": 1, "sheet_id": "trend-core-positions-v1", "rules": str(config["watch_id"]),
        "as_of_utc": as_of_ts.isoformat(), "signal_bar_close_utc": (signal_bar + BAR).isoformat(),
        "valid_until_utc": (signal_bar + 2 * BAR).isoformat(), "leverage": leverage, "equity_usdt": equity,
        "stale_coins": stale, "gross_exposure": gross, "net_exposure": net,
        "long_coins": sum(r["side"] == "LONG" for r in rows), "short_coins": sum(r["side"] == "SHORT" for r in rows),
        "rows": rows,
        "claims": {"orders_sent": False, "live_trading_authorized": False, "descriptive_only": True},
    }


def render_markdown(sheet: Mapping[str, Any]) -> str:
    L, eq = sheet["leverage"], sheet["equity_usdt"]
    lines = [
        "# Trend core: positions to hold",
        "",
        f"Signal from the 8h bar that closed {sheet['signal_bar_close_utc'][:16]} UTC; next update after "
        f"{sheet['valid_until_utc'][:16]} UTC. Sizes are for {eq:,.0f} USDT equity at {L:g}x; scale them to your "
        "account (notional = % of equity x your equity).",
        "",
        f"Gross exposure {sheet['gross_exposure']:.0%} of equity, net {sheet['net_exposure']:+.0%}; "
        f"{sheet['long_coins']} long, {sheet['short_coins']} short.",
        "",
        "Only coins marked OPEN, CLOSE, FLIP or RESIZE need a trade (their signal changed in the last 24h). "
        "Leave HOLD coins as they are, even if the size has drifted.",
        "",
        "| Coin | Action | Side | % of equity | Notional USDT | Quantity | Price |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    order = {"OPEN": 0, "FLIP": 1, "RESIZE": 2, "CLOSE": 3, "HOLD": 4}
    for r in sorted(sheet["rows"], key=lambda r: (order[r["action"]], -abs(r["weight_levered"]))):
        q = r["quantity"]
        lines.append(f"| {r['coin'].replace('_USDT', '')} | {r['action']} | {r['side']} | {r['weight_levered']:+.1%} | "
                     f"{r['notional_usdt']:+,.0f} | {q:+.6g} | {r['reference_price']:.6g} |")
    if sheet["stale_coins"]:
        lines += ["", f"Stale data (last bar older than the others, check by hand): {', '.join(sheet['stale_coins'])}"]
    lines += ["", "Descriptive only: this sheet sends no orders. Use cross margin, one-way mode, market orders."]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    import argparse

    from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", default="config/crypto_trend_core_v1.json")
    p.add_argument("--output-dir", required=True, type=Path)
    p.add_argument("--leverage", type=float, default=3.0)
    p.add_argument("--equity", type=float, default=10_000.0)
    p.add_argument("--as-of", default=None)
    a = p.parse_args(argv)
    config = json.loads(Path(a.config).read_text(encoding="utf-8"))
    as_of = _utc(a.as_of) if a.as_of else pd.Timestamp.now(tz="UTC")
    start = config["source"]["warmup_start_utc"]                # same history as the forward watch, so same episodes
    coins = [c for m in config["groups"].values() for c in m]
    frames = {c: fetch_mexc_futures_klines(c, config["source"]["interval"], start, as_of.isoformat()) for c in coins}
    sheet = build_sheet(config, frames, as_of=as_of, leverage=a.leverage, equity=a.equity)
    a.output_dir.mkdir(parents=True, exist_ok=True)
    (a.output_dir / "positions.json").write_text(json.dumps(sheet, indent=1, sort_keys=True, allow_nan=False) + "\n",
                                                 encoding="utf-8")
    (a.output_dir / "POSITIONS.md").write_text(render_markdown(sheet), encoding="utf-8")
    print(render_markdown(sheet))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
