"""Descriptive capacity / price-impact table for the 70-coin multi-premia blend (V_ALL per-coin implementation).

Usage: PYTHONPATH=src python scripts/blend_capacity_2026_10_12.py
Descriptive only; nothing feeds back into forward watches.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
import pickle

import pandas as pd

from orderflow_edge_lab import capacity as cap
from orderflow_edge_lab.multi_premia_forward import leg_returns
from orderflow_edge_lab.multi_premia_human_forward import coin_targets, leg_weights
from orderflow_edge_lab.trend_portfolio_forward import completed_bars

WINDOW_START = pd.Timestamp("2026-04-05", tz="UTC")
AUMS = [1e4, 1e5, 1e6, 1e7, 1e8]
YS = [1.0, 0.5, 2.0]
TOP_AUMS = [1e6, 1e7]
WARM = "2025-07-01T00:00:00Z"
CACHE = os.path.join(os.environ["TEMP"], "fast_gates_mexc_recent.pkl")
OUT_JSON, OUT_MD = "research/capacity/blend_capacity_v1.json", "research/capacity/blend_capacity_v1.md"
BCFG = json.load(open("config/multi_premia_blend_v1.json", encoding="utf-8"))


def load_cache(as_of):
    """Same loader as scripts/fast_gates_calibrate_2026_10_04.py (cache rebuilt if missing)."""
    if os.path.exists(CACHE):
        return pickle.load(open(CACHE, "rb"))
    from orderflow_edge_lab.basis_convergence import fetch_mexc_funding_history
    from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines
    from orderflow_edge_lab.paper_account import fetch_specs

    def load(s):
        try:
            return (s, fetch_mexc_futures_klines(s, "8h", WARM, as_of.isoformat()),
                    fetch_mexc_funding_history(s, WARM, as_of.isoformat())["funding_rate"])
        except Exception:
            return s, None, None
    with ThreadPoolExecutor(4) as ex:
        got = list(ex.map(load, BCFG["symbols"]))
    frames = {s: f for s, f, _ in got if f is not None}
    funding = {s: fu for s, f, fu in got if f is not None}
    specs = {s: v for s, v in fetch_specs().items() if s in frames}
    pickle.dump((frames, funding, specs), open(CACHE, "wb"))
    return frames, funding, specs


def main() -> int:
    as_of = pd.Timestamp.now(tz="UTC")
    frames, funding, specs = load_cache(as_of)
    clean = {s: completed_bars(f, as_of) for s, f in frames.items()}
    clean = {s: f for s, f in clean.items() if len(f) >= 250}
    legs = leg_returns(BCFG, clean, funding)
    b = BCFG["blend"]
    lw = leg_weights(legs[["S1", "S2", "S3"]], vol_window=int(b["vol_window_days"]), min_obs=int(b["min_obs"]))
    agg = coin_targets(BCFG, clean, funding, lw)
    agg.index = pd.to_datetime(agg.index, utc=True)
    dw_all = agg.diff().abs()
    dw = dw_all[dw_all.index >= WINDOW_START]

    # MEXC USD volume: kline "vol" is in contracts; USD = vol * contractSize * close per 8h bar, summed per UTC day.
    usd8 = pd.DataFrame({s: f["volume"].astype(float) * float(specs[s]["contractSize"]) * f["close"].astype(float)
                         for s, f in clean.items() if s in specs})
    dvol = usd8.sort_index().resample("1D").sum(min_count=3)
    close_d = pd.DataFrame({s: f["close"].astype(float) for s, f in clean.items()}).sort_index().resample("1D").last()
    rets = close_d.pct_change()
    adv, sigma = cap.trailing_liquidity(dvol, rets)
    adv, sigma = adv.reindex(dw.index), sigma.reindex(dw.index)

    # Binance spot cross-check (archive ends 2026-09-30; later days forward-filled, flagged)
    bin_adv = None
    bin_note = ""
    try:
        from orderflow_edge_lab import binance_spot_archive as bsa
        syms = [s.replace("_", "") for s in dw.columns]
        uni = bsa.load_universe(symbols=syms)
        qv = uni["quote_volume"]
        qv.index = pd.to_datetime(qv.index, utc=True)
        qv = qv.rename(columns={s.replace("_", ""): s for s in dw.columns})
        badv = qv.rolling(cap.LIQUIDITY_WINDOW_DAYS, min_periods=20).median().shift(1)
        bin_adv = badv.reindex(badv.index.union(dw.index)).sort_index().ffill().reindex(dw.index).reindex(columns=dw.columns)
        bin_note = (f"Binance archive end {uni['provenance']['end']}; later days forward-filled; "
                    f"{int(bin_adv.iloc[-1].notna().sum())}/{dw.shape[1]} coins matched")
    except Exception as exc:  # cross-check is best-effort
        bin_note = f"Binance cross-check unavailable: {type(exc).__name__}: {exc}"

    ref = cap.REFERENCE_GROSS_EDGE
    res = {"method": {
        "weights": "V_ALL per-coin daily target weights (coin_targets x leg_weights), MEXC data, as in paper_account.build_report",
        "window": f"{dw.index[0].date()}..{dw.index[-1].date()} ({len(dw)} days)", "coins": int(dw.shape[1]),
        "traded_fraction": "|w_t - w_(t-1)|", "impact": "cost_fraction = Y*sigma_daily*sqrt(Q/ADV), Q=|dw|*AUM",
        "adv": ("trailing 30d median daily USD volume, shifted 1 day (causal); MEXC USD = kline vol (contracts) * "
                "contractSize * close per 8h bar, summed by UTC day (units assumed contracts; Binance cross-check tests this)"),
        "sigma": "trailing 30d std of daily close-to-close returns, shifted 1 day",
        "fee_drag": f"{cap.FEE_ROUND_TRIP_BPS} bps round trip = {cap.FEE_ROUND_TRIP_BPS / 2} bps per one-way traded notional",
        "reference_gross_edge_assumption": f"{ref:.0%}/yr (assumed approximate consistent-venue blend return; not measured here)",
        "binance_note": bin_note, "mean_daily_turnover_sum_abs_dw": float(dw.sum(axis=1).mean()),
        "coin_days_dropped_missing_liquidity": int((dw.gt(0) & (adv.isna() | sigma.isna())).to_numpy().sum())},
        "fee_drag_annual": cap.fee_drag(dw), "sources": {}}
    sources = {"mexc": adv}
    if bin_adv is not None:
        sources["binance_spot"] = bin_adv
    for name, a in sources.items():
        block = {"drag_by_aum": {}, "aum_at_share_of_reference_edge": {}, "top10_coins": {}}
        for y in YS:
            block["drag_by_aum"][f"Y={y}"] = {f"{int(x):d}": cap.impact_drag(dw, a, sigma, x, y) for x in AUMS}
            block["aum_at_share_of_reference_edge"][f"Y={y}"] = {
                f"{int(sh * 100)}%": cap.solve_aum_threshold(lambda x, y=y, a=a: cap.impact_drag(dw, a, sigma, x, y), sh * ref)
                for sh in cap.THRESHOLD_SHARES}
        for x in TOP_AUMS:
            per = cap.per_coin_impact_drag(dw, a, sigma, x).sort_values(ascending=False).head(10)
            block["top10_coins"][f"{int(x):d}"] = {k: float(v) for k, v in per.items()}
        res["sources"][name] = block
    json.dump(res, open(OUT_JSON, "w", encoding="utf-8"), indent=1, default=float)

    L = ["# Blend capacity / price impact v1 (descriptive only)", "",
         "Assumptions: square-root law, cost = Y*sigma_d*sqrt(Q/ADV); Q=|dw|*AUM; ADV/sigma trailing 30d (causal).",
         f"Window {res['method']['window']}, {res['method']['coins']} coins. Reference gross edge {ref:.0%}/yr is an ASSUMPTION. "
         f"Fee drag ({cap.FEE_ROUND_TRIP_BPS:g} bps round trip): {res['fee_drag_annual']:.2%}/yr. "
         f"Mean daily sum|dw| = {res['method']['mean_daily_turnover_sum_abs_dw']:.3f}.",
         f"MEXC USD volume = vol(contracts)*contractSize*close. {bin_note}.", ""]
    for name, blk in res["sources"].items():
        L += [f"## Liquidity source: {name}", "", "Annualized impact drag (fraction of AUM per year)", "",
              "| Y | " + " | ".join(f"{x:.0e}" for x in AUMS) + " |", "|---|" + "---|" * len(AUMS)]
        for y in YS:
            L.append(f"| {y} | " + " | ".join(f"{blk['drag_by_aum'][f'Y={y}'][str(int(x))]:.2%}" for x in AUMS) + " |")
        L += ["", "AUM (USD) at which impact drag reaches a share of the reference edge", "",
              "| Y | 25% | 50% | 100% |", "|---|---|---|---|"]
        for y in YS:
            t = blk["aum_at_share_of_reference_edge"][f"Y={y}"]
            L.append(f"| {y} | " + " | ".join(f"{t[k]:.3g}" for k in ("25%", "50%", "100%")) + " |")
        for x in TOP_AUMS:
            L += ["", f"Top 10 impact coins at AUM {x:.0e} (Y=1, drag/yr)", "",
                  ", ".join(f"{k} {v:.2%}" for k, v in blk["top10_coins"][str(int(x))].items())]
        L.append("")
    open(OUT_MD, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
