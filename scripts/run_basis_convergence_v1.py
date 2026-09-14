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


def fetch_kline(symbol: str, kind: str, start: int, end: int) -> pd.DataFrame:
    prefix = {"contract": "contract/kline", "index": "contract/kline/index_price", "fair": "contract/kline/fair_price"}[kind]
    rows: dict[int, tuple[float, float]] = {}
    cursor = start
    while cursor < end:
        chunk_end = min(end - 1, cursor + STEP * 900)
        q = urlencode({"interval": "Min60", "start": cursor, "end": chunk_end})
        data = get_json(f"{BASE}/{prefix}/{symbol}?{q}").get("data")
        if not isinstance(data, dict):
            raise ValueError(f"missing {kind} kline data for {symbol}")
        ts, opn, close = data.get("time"), data.get("open"), data.get("close")
        if not all(isinstance(x, list) for x in (ts, opn, close)):
            raise ValueError(f"malformed {kind} kline arrays for {symbol}")
        for t, o, c in zip(ts, opn, close):
            try:
                ti, ov, cv = int(t), float(o), float(c)
            except (TypeError, ValueError):
                continue
            if start <= ti < end and ov > 0 and cv > 0 and math.isfinite(ov) and math.isfinite(cv):
                rows[ti] = (ov, cv)
        cursor = chunk_end + STEP
        time.sleep(0.1)
    if len(rows) < 500:
        raise ValueError(f"insufficient {kind} history for {symbol}: {len(rows)}")
    idx = sorted(rows)
    return pd.DataFrame({f"{kind}_open": [rows[t][0] for t in idx], f"{kind}_close": [rows[t][1] for t in idx]}, index=pd.to_datetime(idx, unit="s", utc=True))


def fetch_funding(symbol: str) -> pd.DataFrame:
    page = 1
    out = []
    while True:
        q = urlencode({"symbol": symbol, "page_num": page, "page_size": 1000})
        data = get_json(f"{BASE}/contract/funding_rate/history?{q}").get("data")
        if not isinstance(data, dict) or not isinstance(data.get("resultList"), list):
            raise ValueError(f"malformed funding history for {symbol}")
        for item in data["resultList"]:
            if not isinstance(item, dict):
                continue
            try:
                out.append((pd.to_datetime(int(item["settleTime"]), unit="ms", utc=True), float(item["fundingRate"])))
            except (KeyError, TypeError, ValueError):
                continue
        total_pages = int(data.get("totalPage") or 1)
        if page >= total_pages:
            break
        page += 1
        time.sleep(0.1)
    if not out:
        raise ValueError(f"no funding history for {symbol}")
    frame = pd.DataFrame(out, columns=["timestamp", "funding_rate"]).drop_duplicates("timestamp").sort_values("timestamp")
    return frame.set_index("timestamp")


def pf(values: pd.Series) -> float:
    pos = values[values > 0].sum()
    neg = -values[values < 0].sum()
    if neg <= 0:
        return 1_000_000.0 if pos > 0 else 0.0
    return float(pos / neg)


def fold_id(index: pd.DatetimeIndex, start: pd.Timestamp) -> np.ndarray:
    return ((index - start).days // 21).astype(int)


def funding_complete(funding: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, max_gap_h: int) -> bool:
    f = funding.loc[(funding.index >= start) & (funding.index < end)]
    if len(f) < 10:
        return False
    if f.index.min() > start + pd.Timedelta(hours=max_gap_h):
        return False
    if f.index.max() < end - pd.Timedelta(hours=max_gap_h):
        return False
    gaps = f.index.to_series().diff().dropna().dt.total_seconds().div(3600)
    return bool((gaps <= max_gap_h).all())


def state_metrics(per_symbol: dict[str, pd.DataFrame], window: int, hold: int) -> dict:
    cells = []
    for symbol, df in per_symbol.items():
        basis = df["basis_bps"]
        mu = basis.rolling(window, min_periods=window).mean()
        sd = basis.rolling(window, min_periods=window).std(ddof=0).replace(0, np.nan)
        z = (basis - mu) / sd
        target = -np.sign(basis) * (basis.shift(-hold) - basis)
        tmp = pd.DataFrame({"score": np.sign(basis) * z.abs(), "target": target, "fold": df["fold"]}).dropna()
        for fid, g in tmp.groupby("fold"):
            if len(g) < 30 or g["score"].nunique() < 4 or g["target"].nunique() < 4:
                continue
            rho = g["score"].corr(g["target"], method="spearman")
            if pd.notna(rho):
                cells.append((symbol, int(fid), float(rho)))
    c = pd.DataFrame(cells, columns=["symbol", "fold", "rho"])
    if c.empty:
        return {"median_fold_rho": np.nan, "positive_fold_fraction": 0.0, "positive_symbol_fraction": 0.0, "folds": 0, "symbols": 0}
    by_fold = c.groupby("fold")["rho"].median()
    by_symbol = c.groupby("symbol")["rho"].median()
    return {"median_fold_rho": float(by_fold.median()), "positive_fold_fraction": float((by_fold > 0).mean()), "positive_symbol_fraction": float((by_symbol > 0).mean()), "folds": int(len(by_fold)), "symbols": int(len(by_symbol))}


def make_trades(df: pd.DataFrame, funding: pd.DataFrame, window: int, threshold: float, hold: int, symbol: str) -> pd.DataFrame:
    basis = df["basis_bps"]
    mu = basis.rolling(window, min_periods=window).mean()
    sd = basis.rolling(window, min_periods=window).std(ddof=0).replace(0, np.nan)
    z = (basis - mu) / sd
    rows = []
    next_free = -1
    idx = df.index
    for i in range(window, len(df) - hold - 1):
        if i <= next_free or not np.isfinite(z.iloc[i]) or abs(z.iloc[i]) < threshold:
            continue
        ei, xi = i + 1, i + 1 + hold
        if int(df["fold"].iloc[i]) != int(df["fold"].iloc[xi]):
            continue
        entry, exit_ = float(df["contract_open"].iloc[ei]), float(df["contract_open"].iloc[xi])
        if entry <= 0 or exit_ <= 0:
            continue
        side = -1 if basis.iloc[i] > 0 else 1
        gross = side * (exit_ / entry - 1.0) * 10000.0
        ft = funding.loc[(funding.index >= idx[ei]) & (funding.index < idx[xi])]
        fund_bps = float((-side * ft["funding_rate"] * 10000.0).sum())
        rows.append({"symbol": symbol, "fold": int(df["fold"].iloc[i]), "signal_time": idx[i], "entry_time": idx[ei], "exit_time": idx[xi], "side": side, "gross_bps": gross, "funding_bps": fund_bps})
        next_free = xi
    return pd.DataFrame(rows)


def economic_metrics(trades: pd.DataFrame, cost: float) -> dict:
    if trades.empty:
        return {"trades": 0, "median_fold_net_bps": np.nan, "median_fold_pf": np.nan, "positive_fold_fraction": 0.0, "positive_symbol_fraction": 0.0}
    t = trades.copy()
    t["net"] = t["gross_bps"] + t["funding_bps"] - cost
    by_fold = t.groupby("fold")["net"].agg(["mean", pf])
    by_symbol = t.groupby("symbol")["net"].mean()
    return {"trades": int(len(t)), "median_fold_net_bps": float(by_fold["mean"].median()), "median_fold_pf": float(by_fold["pf"].median()), "positive_fold_fraction": float((by_fold["mean"] > 0).mean()), "positive_symbol_fraction": float((by_symbol > 0).mean())}


def randomized_p(trades: pd.DataFrame, cost: float, iterations: int = 2000) -> float:
    if trades.empty:
        return 1.0
    obs = float((trades["gross_bps"] + trades["funding_bps"] - cost).mean())
    rng = np.random.default_rng(20260914)
    vals = []
    for _ in range(iterations):
        pieces = []
        for _, g in trades.groupby(["symbol", "fold"]):
            signs = rng.choice([-1.0, 1.0], size=len(g))
            # Flip both price and funding exposure when direction is randomized.
            pieces.extend((g["gross_bps"].to_numpy() * signs + g["funding_bps"].to_numpy() * signs - cost).tolist())
        vals.append(float(np.mean(pieces)))
    return float((1 + np.sum(np.asarray(vals) >= obs)) / (iterations + 1))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/basis_convergence_v1.json")
    ap.add_argument("--out", default="research/basis_convergence_v1")
    args = ap.parse_args()
    cfg = json.load(open(args.config, encoding="utf-8"))
    assert cfg["outcomes_inspected_before_freeze"] is False
    assert cfg["state_layer"]["required_before_strategy_pnl"] is True
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    start = pd.Timestamp(cfg["data"]["start"], tz="UTC"); end = pd.Timestamp(cfg["data"]["end_exclusive"], tz="UTC")
    start_s, end_s = int(start.timestamp()), int(end.timestamp())

    data = {}; funding = {}; quality = []
    for symbol in cfg["data"]["symbols"]:
        try:
            c = fetch_kline(symbol, "contract", start_s, end_s)
            i = fetch_kline(symbol, "index", start_s, end_s)
            f = fetch_kline(symbol, "fair", start_s, end_s)
            x = c.join(i, how="inner").join(f, how="inner")
            x["basis_bps"] = 10000.0 * (x["fair_close"] / x["index_close"] - 1.0)
            x["fold"] = fold_id(x.index, start)
            fr = fetch_funding(symbol)
            complete = funding_complete(fr, start, end, int(cfg["strategy_translation"]["funding"]["maximum_allowed_gap_hours_between_records"]))
            quality.append({"symbol": symbol, "bars": len(x), "funding_records": len(fr.loc[(fr.index>=start)&(fr.index<end)]), "funding_complete": complete})
            if complete:
                data[symbol] = x
                funding[symbol] = fr
        except Exception as exc:
            quality.append({"symbol": symbol, "bars": 0, "funding_records": 0, "funding_complete": False, "error": f"{type(exc).__name__}: {exc}"})
    pd.DataFrame(quality).to_csv(out / "data_quality.csv", index=False)
    if len(data) < int(cfg["dependence"]["minimum_symbols"]):
        raise SystemExit(f"insufficient symbols with complete required data: {len(data)}")

    state_rows=[]; trade_map={}
    for window in cfg["state_layer"]["windows"]:
        for hold in cfg["state_layer"]["hold_bars"]:
            sm=state_metrics(data, int(window), int(hold))
            state_pass=(sm["folds"]>=cfg["dependence"]["minimum_folds"] and sm["symbols"]>=cfg["dependence"]["minimum_symbols"] and sm["median_fold_rho"]>0 and sm["positive_fold_fraction"]>=cfg["state_layer"]["gate"]["minimum_positive_fold_fraction"] and sm["positive_symbol_fraction"]>=cfg["state_layer"]["gate"]["minimum_positive_symbol_fraction"])
            for th in cfg["state_layer"]["threshold_z"]:
                row={"window":window,"threshold_z":th,"hold_bars":hold,**sm,"state_pass":state_pass}; state_rows.append(row)
                if state_pass:
                    ts=[]
                    for symbol,df in data.items():
                        t=make_trades(df,funding[symbol],int(window),float(th),int(hold),symbol)
                        if not t.empty: ts.append(t)
                    trade_map[(window,float(th),hold)] = pd.concat(ts,ignore_index=True) if ts else pd.DataFrame()
    state_df=pd.DataFrame(state_rows); state_df.to_csv(out/"state.csv",index=False)

    econ=[]
    for key,trades in trade_map.items():
        window,th,hold=key
        for cost in cfg["strategy_translation"]["round_trip_execution_cost_bps"]:
            m=economic_metrics(trades,float(cost))
            if trades.empty:
                rev_mean=placebo_mean=np.nan; pval=1.0
            else:
                rev=trades.copy(); rev["gross_bps"]=-rev["gross_bps"]; rev["funding_bps"]=-rev["funding_bps"]
                rev_mean=float((rev["gross_bps"]+rev["funding_bps"]-float(cost)).mean())
                pl=trades.copy(); pl=pl.sort_values(["symbol","fold","entry_time"]); pl["alt_side"]=pl.groupby(["symbol","fold"]).cumcount().mod(2).map({0:1,1:-1})
                original_side=pl["side"].to_numpy(); alt_side=pl["alt_side"].to_numpy(); ratio=alt_side/original_side
                placebo_mean=float((pl["gross_bps"]*ratio+pl["funding_bps"]*ratio-float(cost)).mean())
                pval=randomized_p(trades,float(cost),int(cfg["controls"]["within_symbol_fold_sign_permutation_iterations"]))
            base=(m["trades"]>=cfg["screening_gate"]["minimum_total_trades"] and m["median_fold_net_bps"]>0 and m["median_fold_pf"]>1 and m["positive_fold_fraction"]>=cfg["screening_gate"]["minimum_positive_fold_fraction"] and m["positive_symbol_fraction"]>=cfg["screening_gate"]["minimum_positive_symbol_fraction"] and m["median_fold_net_bps"]>rev_mean and m["median_fold_net_bps"]>placebo_mean and pval<cfg["screening_gate"]["randomized_direction_p_lt"])
            econ.append({"window":window,"threshold_z":th,"hold_bars":hold,"cost_bps":cost,**m,"reversed_mean_net_bps":rev_mean,"basis_sign_removed_placebo_mean_net_bps":placebo_mean,"randomized_p":pval,"base_pass":base})
    econ_df=pd.DataFrame(econ)
    primary=float(cfg["strategy_translation"]["primary_cost_bps"])
    keys=list(trade_map)
    def neighbor_support(row):
        if row["cost_bps"]!=primary or not row["base_pass"]: return False
        for k in keys:
            diffs=sum([k[0]!=row["window"],k[1]!=row["threshold_z"],k[2]!=row["hold_bars"]])
            if diffs!=1: continue
            q=econ_df[(econ_df.window==k[0])&(econ_df.threshold_z==k[1])&(econ_df.hold_bars==k[2])&(econ_df.cost_bps==primary)]
            if len(q) and bool(q.iloc[0]["base_pass"]): return True
        return False
    if not econ_df.empty:
        econ_df["parameter_neighborhood_support"]=econ_df.apply(neighbor_support,axis=1)
        econ_df["economic_pass"]=econ_df["base_pass"] & econ_df["parameter_neighborhood_support"]
    econ_df.to_csv(out/"economics.csv",index=False)
    summary={"protocol":cfg["protocol_name"],"symbols_with_complete_data":len(data),"state_variants":len(state_df),"state_passes":int(state_df.state_pass.sum()),"economic_rows":len(econ_df),"primary_economic_passes":int(econ_df[econ_df.cost_bps==primary].economic_pass.sum()) if len(econ_df) else 0,"claims":cfg["claims"]}
    (out/"summary.json").write_text(json.dumps(summary,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(summary,indent=2))


if __name__ == "__main__":
    main()
