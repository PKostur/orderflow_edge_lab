"""Forward evaluation of the four news-sentiment-v1 strategies (config/news_sentiment_v1.json). Forward days only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from orderflow_edge_lab.multi_premia_forward import blend, leg_returns
from orderflow_edge_lab.strategy_zoo import _basket_weights, run_targets
from orderflow_edge_lab.trend_portfolio_forward import _utc, completed_bars, summarize
from orderflow_edge_lab.xs_premia import daily_funding_panel, daily_open_panel

WATCH_ID = "news-sentiment-v1-forward"


def panels(daily: Mapping[str, Any], index: pd.DatetimeIndex, coins: list[str]) -> tuple[pd.Series, pd.DataFrame, pd.DataFrame]:
    """Market score, per-coin mention counts and score sums, keyed by item day (not yet lagged)."""
    mk = pd.Series({pd.Timestamp(d, tz="UTC"): v["score"] for d, v in daily.get("market", {}).items() if v.get("score") is not None}, dtype=float)
    mentions = pd.DataFrame(0.0, index=index, columns=coins)
    sums = pd.DataFrame(0.0, index=index, columns=coins)
    for c, days in daily.get("coins", {}).items():
        col = f"{c}_USDT"
        if col not in coins:
            continue
        for d, v in days.items():
            t = pd.Timestamp(d, tz="UTC")
            if t in mentions.index:
                mentions.at[t, col] = v["mentions"]
                sums.at[t, col] = v["score_sum"]
    return mk.reindex(index), mentions, sums


def n1_targets(mentions: pd.DataFrame, sums: pd.DataFrame, *, min_mentions: int = 3, min_coins: int = 6, k: int = 3) -> pd.DataFrame:
    m7, s7 = mentions.shift(1).rolling(7, min_periods=1).sum(), sums.shift(1).rolling(7, min_periods=1).sum()
    out = pd.DataFrame(0.0, index=mentions.index, columns=mentions.columns)
    w = pd.Series(0.0, index=mentions.columns)
    for d in mentions.index:
        if d.dayofweek == 0:
            elig = s7.loc[d][m7.loc[d] >= min_mentions]
            w = pd.Series(0.0, index=mentions.columns)
            if len(elig) >= min_coins:
                order = elig.sort_values()
                w[order.index[-k:]] = 0.5 / k
                w[order.index[:k]] = -0.5 / k
        out.loc[d] = w
    return out


def n2_targets(mentions: pd.DataFrame, sums: pd.DataFrame, opens: pd.DataFrame, *, mult: float = 3.0, hold: int = 7) -> pd.DataFrame:
    m3 = mentions.shift(1).rolling(3, min_periods=3).sum()
    s3 = sums.shift(1).rolling(3, min_periods=3).sum()
    base = m3.shift(3).rolling(30, min_periods=30).mean()
    trig = (m3 >= mult * base) & (base > 0) & (s3 > 0)
    held = trig.astype(float).rolling(hold, min_periods=1).max().fillna(0.0)
    n = held.sum(axis=1)
    longs = held.div(n.where(n > 0), axis=0).fillna(0.0) * 0.5
    hedge = _basket_weights(opens, list(opens.columns)).reindex(held.index).fillna(0.0).mul((n > 0).astype(float) * -0.5, axis=0)
    return longs + hedge


def n3_targets(market: pd.Series, opens: pd.DataFrame) -> pd.DataFrame:
    lagged = market.shift(1)
    m7 = lagged.rolling(7, min_periods=5).mean()
    base = lagged.shift(7).rolling(30, min_periods=20).mean()
    side = np.sign((m7 - base).fillna(0.0))
    return _basket_weights(opens, list(opens.columns)).mul(side, axis=0)


def n4_scale(market: pd.Series) -> pd.Series:
    lagged = market.shift(1)
    m3 = lagged.rolling(3, min_periods=2).mean()
    q10 = m3.shift(1).rolling(60, min_periods=30).quantile(0.10)
    return pd.Series(np.where(m3 <= q10, 0.5, 1.0), index=market.index)


def build_report(cfg: Mapping[str, Any], blend_cfg: Mapping[str, Any], daily: Mapping[str, Any], frames: Mapping[str, pd.DataFrame],
                 funding: Mapping[str, pd.Series], *, as_of: Any, cost_bps: float = 20.0) -> dict[str, Any]:
    as_of_ts, start = _utc(as_of), _utc(cfg["strategies"]["prospective_start_utc"])
    clean = {s: completed_bars(f, as_of_ts) for s, f in frames.items()}
    clean = {s: f for s, f in clean.items() if len(f) >= 100}
    opens = daily_open_panel(clean)
    fund = daily_funding_panel(funding, opens.index)
    market, mentions, sums = panels(daily, opens.index, list(opens.columns))
    books = pd.DataFrame({
        "N1_news_momentum": run_targets(n1_targets(mentions, sums), opens, fund, cost_bps=cost_bps),
        "N2_attention_breakout": run_targets(n2_targets(mentions, sums, opens), opens, fund, cost_bps=cost_bps),
        "N3_market_tone_following": run_targets(n3_targets(market, opens), opens, fund, cost_bps=cost_bps),
    })
    books.index = books.index + pd.Timedelta(days=1)
    legs = leg_returns(blend_cfg, clean, funding)
    b = blend_cfg["blend"]
    scale = n4_scale(market)
    scale.index = scale.index + pd.Timedelta(days=1)
    base = blend(legs[["S1", "S2", "S3"]], vol_window=int(b["vol_window_days"]), min_obs=int(b["min_obs"]))
    paused = blend(legs[["S1", "S2", "S3"]].assign(S2=legs["S2"] * scale.reindex(legs.index).fillna(1.0)),
                   vol_window=int(b["vol_window_days"]), min_obs=int(b["min_obs"]))
    books["N4_blend_with_panic_pause"] = paused
    books["N4_reference_blend"] = base
    fwd = books[(books.index - pd.Timedelta(days=1)) >= start]
    days = int(fwd["N3_market_tone_following"].dropna().shape[0])
    return {
        "schema_version": 1, "watch_id": WATCH_ID, "protocol": cfg["protocol_id"],
        "status": "PRE_START" if days == 0 else "COLLECTING",
        "as_of_utc": as_of_ts.isoformat(), "prospective_start_utc": start.isoformat(),
        "news_days_available": len(daily.get("market", {})),
        "forward": {k: summarize(fwd[k].dropna(), nw_lags=5) for k in fwd.columns},
        "daily_returns": {k: {t.isoformat(): float(v) for t, v in fwd[k].dropna().items()} for k in fwd.columns},
        "review_window_open": days >= int(cfg["review"]["verdict_after_days"]),
        "claims": dict(cfg["claims"]),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    from concurrent.futures import ThreadPoolExecutor

    from orderflow_edge_lab.basis_convergence import fetch_mexc_funding_history
    from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines

    p = argparse.ArgumentParser(description="Score the news-sentiment-v1 strategies on forward days.")
    p.add_argument("--config", default="config/news_sentiment_v1.json")
    p.add_argument("--blend-config", default="config/multi_premia_blend_v1.json")
    p.add_argument("--daily", required=True, help="daily.json from the collector")
    p.add_argument("--output", required=True)
    a = p.parse_args(argv)
    cfg = json.loads(Path(a.config).read_text(encoding="utf-8"))
    bcfg = json.loads(Path(a.blend_config).read_text(encoding="utf-8"))
    daily = json.loads(Path(a.daily).read_text(encoding="utf-8"))
    as_of = pd.Timestamp.now(tz="UTC")
    warm = bcfg["source"]["warmup_start_utc"]

    def load(s):
        try:
            return (s, fetch_mexc_futures_klines(s, "8h", warm, as_of.isoformat()),
                    fetch_mexc_funding_history(s, warm, as_of.isoformat())["funding_rate"])
        except Exception:
            return s, None, None

    with ThreadPoolExecutor(4) as ex:
        got = list(ex.map(load, bcfg["symbols"]))
    frames = {s: f for s, f, _ in got if f is not None}
    funding = {s: fu for s, f, fu in got if f is not None}
    report = build_report(cfg, bcfg, daily, frames, funding, as_of=as_of)
    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    Path(a.output).write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "news_days": report["news_days_available"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
