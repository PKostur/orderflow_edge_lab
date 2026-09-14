from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

BASE = "https://api.mexc.com/api/v1"
STEP = 3600


def get_json(url: str) -> dict:
    req = Request(url, headers={"Accept": "application/json", "User-Agent": "orderflow-edge-lab/1.0"})
    with urlopen(req, timeout=30) as r:
        payload = json.loads(r.read(16_000_000).decode("utf-8"))
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise ValueError(f"bad MEXC payload for {url}: {payload}")
    return payload


def fetch_kline(symbol: str, start: int, end: int) -> pd.DataFrame:
    rows: dict[int, tuple[float, float]] = {}
    cursor = start
    while cursor < end:
        chunk_end = min(end - 1, cursor + STEP * 900)
        q = urlencode({"interval": "Min60", "start": cursor, "end": chunk_end})
        data = get_json(f"{BASE}/contract/kline/{symbol}?{q}").get("data")
        if not isinstance(data, dict):
            raise ValueError(f"missing kline data for {symbol}")
        ts, opn, close = data.get("time"), data.get("open"), data.get("close")
        if not all(isinstance(x, list) for x in (ts, opn, close)):
            raise ValueError(f"malformed kline arrays for {symbol}")
        for t, o, c in zip(ts, opn, close):
            try:
                ti, ov, cv = int(t), float(o), float(c)
            except (TypeError, ValueError):
                continue
            if start <= ti < end and ov > 0 and cv > 0 and math.isfinite(ov) and math.isfinite(cv):
                rows[ti] = (ov, cv)
        cursor = chunk_end + STEP
        time.sleep(0.08)
    if len(rows) < 500:
        raise ValueError(f"insufficient history for {symbol}: {len(rows)}")
    idx = sorted(rows)
    return pd.DataFrame({"open": [rows[t][0] for t in idx], "close": [rows[t][1] for t in idx]}, index=pd.to_datetime(idx, unit="s", utc=True))


def pf(values: pd.Series) -> float:
    pos = values[values > 0].sum()
    neg = -values[values < 0].sum()
    if neg <= 0:
        return 1_000_000.0 if pos > 0 else 0.0
    return float(pos / neg)


def build_panel(alt: pd.DataFrame, btc: pd.DataFrame, start: pd.Timestamp, beta_window: int, impulse_lb: int, lag: int, horizon: int) -> pd.DataFrame:
    x = alt.rename(columns={"open": "alt_open", "close": "alt_close"}).join(
        btc.rename(columns={"open": "btc_open", "close": "btc_close"}), how="inner"
    )
    ar = np.log(x["alt_close"]).diff()
    br = np.log(x["btc_close"]).diff()
    cov = ar.rolling(beta_window, min_periods=beta_window).cov(br)
    var = br.rolling(beta_window, min_periods=beta_window).var().replace(0, np.nan)
    beta = (cov / var).clip(-5.0, 5.0)
    btc_impulse = np.log(x["btc_close"].shift(lag) / x["btc_close"].shift(lag + impulse_lb))
    alt_future = np.log(x["alt_close"].shift(-horizon) / x["alt_close"])
    btc_future = np.log(x["btc_close"].shift(-horizon) / x["btc_close"])
    x["beta"] = beta
    x["score"] = btc_impulse
    x["target"] = alt_future - beta * btc_future
    x["fold"] = ((x.index - start).days // 21).astype(int)
    return x


def state_metrics(panels: dict[str, pd.DataFrame], cfg: dict) -> dict:
    cells = []
    observations = 0
    for symbol, x in panels.items():
        tmp = x[["score", "target", "fold"]].dropna()
        observations += len(tmp)
        for fid, g in tmp.groupby("fold"):
            if len(g) < 30 or g["score"].nunique() < 4 or g["target"].nunique() < 4:
                continue
            rho = g["score"].corr(g["target"], method="spearman")
            if pd.notna(rho):
                cells.append((symbol, int(fid), float(rho)))
    c = pd.DataFrame(cells, columns=["symbol", "fold", "rho"])
    if c.empty:
        return {"observations": observations, "folds": 0, "symbols": 0, "median_fold_rho": np.nan, "positive_fold_fraction": 0.0, "positive_symbol_fraction": 0.0}
    by_fold = c.groupby("fold")["rho"].median()
    by_symbol = c.groupby("symbol")["rho"].median()
    return {
        "observations": observations,
        "folds": int(len(by_fold)),
        "symbols": int(len(by_symbol)),
        "median_fold_rho": float(by_fold.median()),
        "positive_fold_fraction": float((by_fold > 0).mean()),
        "positive_symbol_fraction": float((by_symbol > 0).mean()),
    }


def clustered_state_permutation_p(panels: dict[str, pd.DataFrame], observed: float, iterations: int) -> float:
    if not np.isfinite(observed):
        return 1.0
    rng = np.random.default_rng(20260914)
    null = []
    prepared = []
    for symbol, x in panels.items():
        t = x[["score", "target", "fold"]].dropna()
        for fid, g in t.groupby("fold"):
            if len(g) >= 30 and g["score"].nunique() >= 4 and g["target"].nunique() >= 4:
                prepared.append((symbol, int(fid), g["score"].to_numpy(), g["target"].to_numpy()))
    for _ in range(iterations):
        rows = []
        for symbol, fid, score, target in prepared:
            p = rng.permutation(score)
            rho = pd.Series(p).corr(pd.Series(target), method="spearman")
            if pd.notna(rho): rows.append((symbol, fid, float(rho)))
        d = pd.DataFrame(rows, columns=["symbol", "fold", "rho"])
        if not d.empty:
            null.append(float(d.groupby("fold")["rho"].median().median()))
    if not null:
        return 1.0
    return float((1 + np.sum(np.asarray(null) >= observed)) / (len(null) + 1))


def make_trades(symbol: str, x: pd.DataFrame, horizon: int) -> pd.DataFrame:
    rows = []
    next_free = -1
    for i in range(len(x) - horizon - 2):
        if i <= next_free:
            continue
        score = x["score"].iloc[i]
        if not np.isfinite(score) or score == 0:
            continue
        ei, xi = i + 1, i + 1 + horizon
        if int(x["fold"].iloc[i]) != int(x["fold"].iloc[xi]):
            continue
        entry, exit_ = float(x["alt_open"].iloc[ei]), float(x["alt_open"].iloc[xi])
        bentry, bexit = float(x["btc_open"].iloc[ei]), float(x["btc_open"].iloc[xi])
        beta = float(x["beta"].iloc[i])
        if min(entry, exit_, bentry, bexit) <= 0 or not np.isfinite(beta):
            continue
        side = 1.0 if score > 0 else -1.0
        alt_gross = side * (exit_ / entry - 1.0) * 10000.0
        hedge_gross = -side * beta * (bexit / bentry - 1.0) * 10000.0
        rows.append({"symbol": symbol, "fold": int(x["fold"].iloc[i]), "side": side, "beta": beta, "alt_gross_bps": alt_gross, "hedged_gross_bps": alt_gross + hedge_gross})
        next_free = xi
    return pd.DataFrame(rows)


def econ_metrics(trades: pd.DataFrame, cost: float, gross_col: str = "alt_gross_bps") -> dict:
    if trades.empty:
        return {"trades": 0, "median_fold_net_bps": np.nan, "median_fold_pf": np.nan, "positive_fold_fraction": 0.0, "positive_symbol_fraction": 0.0, "mean_net_bps": np.nan}
    t = trades.copy(); t["net"] = t[gross_col] - cost
    bf = t.groupby("fold")["net"].agg(["mean", pf])
    bs = t.groupby("symbol")["net"].mean()
    return {"trades": int(len(t)), "median_fold_net_bps": float(bf["mean"].median()), "median_fold_pf": float(bf["pf"].median()), "positive_fold_fraction": float((bf["mean"] > 0).mean()), "positive_symbol_fraction": float((bs > 0).mean()), "mean_net_bps": float(t["net"].mean())}


def main() -> None:
    ap = argparse.ArgumentParser(); ap.add_argument("--config", default="config/btc_lead_lag_v1.json"); ap.add_argument("--out", default="research/btc_lead_lag_v1")
    args = ap.parse_args(); cfg = json.load(open(args.config, encoding="utf-8"))
    assert cfg["outcomes_inspected_before_freeze"] is False
    assert cfg["state_layer"]["required_before_strategy_pnl"] is True
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    start = pd.Timestamp(cfg["data"]["start"], tz="UTC"); end = pd.Timestamp(cfg["data"]["end_exclusive"], tz="UTC")
    btc = fetch_kline(cfg["data"]["context_symbol"], int(start.timestamp()), int(end.timestamp()))
    alts = {}; quality = []
    for s in cfg["data"]["symbols"]:
        try:
            d = fetch_kline(s, int(start.timestamp()), int(end.timestamp())); alts[s] = d; quality.append({"symbol": s, "bars": len(d), "ok": True})
        except Exception as exc:
            quality.append({"symbol": s, "bars": 0, "ok": False, "error": f"{type(exc).__name__}: {exc}"})
    pd.DataFrame(quality).to_csv(out / "data_quality.csv", index=False)
    if len(alts) < cfg["dependence"]["minimum_symbols"]: raise SystemExit("insufficient symbols")

    rows = []; trade_maps = {}
    f = cfg["feature_family"]; sg = cfg["state_layer"]
    for beta_w in f["rolling_beta_window_bars"]:
      for lb in f["btc_impulse_lookback_bars"]:
       for lag in f["lead_lag_bars"]:
        for h in f["future_horizon_bars"]:
            panels = {s: build_panel(d, btc, start, int(beta_w), int(lb), int(lag), int(h)) for s,d in alts.items()}
            m = state_metrics(panels, cfg)
            p = clustered_state_permutation_p(panels, m["median_fold_rho"], int(sg["clustered_permutations"]))
            passed = (m["observations"] >= sg["minimum_total_observations"] and m["folds"] >= cfg["dependence"]["minimum_folds"] and m["symbols"] >= cfg["dependence"]["minimum_symbols"] and m["median_fold_rho"] > sg["median_fold_spearman_gt"] and m["positive_fold_fraction"] >= sg["minimum_positive_fold_fraction"] and m["positive_symbol_fraction"] >= sg["minimum_positive_symbol_fraction"] and p < sg["permutation_p_lt"])
            key = (beta_w, lb, lag, h); rows.append({"beta_window":beta_w,"impulse_lookback":lb,"lag":lag,"horizon":h,**m,"permutation_p":p,"state_pass":passed})
            if passed:
                ts=[make_trades(s,x,int(h)) for s,x in panels.items()]; ts=[t for t in ts if not t.empty]; trade_maps[key]=pd.concat(ts,ignore_index=True) if ts else pd.DataFrame()
    state = pd.DataFrame(rows); state.to_csv(out / "state.csv", index=False)

    econ=[]
    for key,trades in trade_maps.items():
        beta_w,lb,lag,h=key
        for cost in cfg["strategy_translation"]["round_trip_cost_bps"]:
            m=econ_metrics(trades,float(cost)); rev=econ_metrics(trades.assign(alt_gross_bps=-trades["alt_gross_bps"]),float(cost)); hedged=econ_metrics(trades,float(cost)*2.0,"hedged_gross_bps")
            base=(m["trades"]>=cfg["screening_gate"]["minimum_total_trades"] and m["median_fold_net_bps"]>0 and m["median_fold_pf"]>1 and m["positive_fold_fraction"]>=cfg["screening_gate"]["minimum_positive_fold_fraction"] and m["positive_symbol_fraction"]>=cfg["screening_gate"]["minimum_positive_symbol_fraction"] and m["mean_net_bps"]>rev["mean_net_bps"])
            econ.append({"beta_window":beta_w,"impulse_lookback":lb,"lag":lag,"horizon":h,"cost_bps":cost,**m,"reversed_mean_net_bps":rev["mean_net_bps"],"hedged_control_mean_net_bps":hedged["mean_net_bps"],"base_pass":base})
    edf=pd.DataFrame(econ); edf.to_csv(out / "economics.csv", index=False)
    summary={"protocol":cfg["protocol_name"],"symbols_with_data":len(alts),"state_variants":len(state),"state_passes":int(state["state_pass"].sum()) if not state.empty else 0,"economic_rows":len(edf),"primary_economic_passes":int(edf.loc[edf["cost_bps"]==cfg["strategy_translation"]["primary_cost_bps"],"base_pass"].sum()) if not edf.empty else 0,"claims":cfg["claims"]}
    (out/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8"); print(json.dumps(summary,indent=2))

if __name__ == "__main__": main()
