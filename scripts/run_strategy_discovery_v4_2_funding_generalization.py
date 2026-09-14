from __future__ import annotations

import argparse
import json
from pathlib import Path
import math

import numpy as np
import pandas as pd

START = pd.Timestamp("2025-09-01", tz="UTC")
END = pd.Timestamp("2026-08-01", tz="UTC")
DEV_FOLDS = set(range(15))
COSTS = {"low": 12.0, "primary": 16.0, "high": 20.0}
K = 3
HOLD = 72
ORIGINAL_NON_BTC = ["ETH","SOL","XRP","DOGE","BNB","ADA","LINK","SUI","ENA"]


def pf(vals) -> float:
    a = np.asarray(vals, float)
    pos = a[a > 0].sum(); neg = -a[a < 0].sum()
    return 999.0 if neg <= 0 and pos > 0 else (0.0 if neg <= 0 else float(pos / neg))


def rho(a, b) -> float:
    aa = np.asarray(a, float); bb = np.asarray(b, float)
    m = np.isfinite(aa) & np.isfinite(bb)
    if m.sum() < 20:
        return np.nan
    return float(pd.Series(aa[m]).rank().corr(pd.Series(bb[m]).rank()))


def clean(v):
    if isinstance(v, (np.floating, float)):
        x = float(v)
        return x if math.isfinite(x) else None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, dict):
        return {k: clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [clean(x) for x in v]
    return v


def load_symbol(data_dir: Path, symbol: str, idx: pd.DatetimeIndex) -> dict[str, pd.Series]:
    fut = pd.read_csv(data_dir / f"{symbol}_futures_1h.csv", parse_dates=["timestamp"]).set_index("timestamp").sort_index()
    fund = pd.read_csv(data_dir / f"{symbol}_funding.csv", parse_dates=["timestamp"]).set_index("timestamp").sort_index()
    fut.index = pd.to_datetime(fut.index, utc=True).floor("h")
    fut = fut[~fut.index.duplicated(keep="last")]
    op = pd.to_numeric(fut["open"], errors="coerce").reindex(idx)
    cl = pd.to_numeric(fut["close"], errors="coerce").reindex(idx)
    if len(fund):
        fund.index = pd.to_datetime(fund.index, utc=True).floor("h")
        rate = pd.to_numeric(fund["funding_rate"], errors="coerce")
        rate = rate.groupby(fund.index).sum().sort_index()
    else:
        rate = pd.Series(dtype=float)
    settle = rate.reindex(idx, fill_value=0.0).astype(float)
    fcum = settle.cumsum()
    return {"open":op, "close":cl, "settle":settle, "fcum":fcum, "fund_raw":rate}


def build_context(data_dir: Path, alpha_symbols: list[str]):
    idx = pd.date_range(START, END, freq="h", inclusive="left")
    symbols = list(dict.fromkeys(["BTC"] + alpha_symbols))
    data = {s: load_symbol(data_dir, s, idx) for s in symbols}
    btc_ret = data["BTC"]["close"].pct_change()
    beta = pd.DataFrame(index=idx, columns=alpha_symbols, dtype=float)
    for s in alpha_symbols:
        r = data[s]["close"].pct_change()
        cov = r.rolling(192, min_periods=96).cov(btc_ret)
        var = btc_ret.rolling(192, min_periods=96).var().replace(0, np.nan)
        beta[s] = (cov / var).shift(1)
    return idx, data, beta


def funding_mean_on_hour(data: dict, idx: pd.DatetimeIndex, s: str, nsett: int) -> pd.Series:
    raw = data[s]["fund_raw"]
    if raw.empty:
        return pd.Series(np.nan, index=idx)
    mean = raw.rolling(nsett, min_periods=nsett).mean()
    return mean.reindex(idx, method="ffill")


def evaluate(data_dir: Path, alpha_symbols: list[str], nsett: int, *, include_trade_details: bool = True) -> dict:
    idx, data, betas = build_context(data_dir, alpha_symbols)
    fm = pd.DataFrame({s: funding_mean_on_hour(data, idx, s, nsett) for s in alpha_symbols}, index=idx)
    fold = np.floor((idx - START) / pd.Timedelta(days=21)).astype(int)
    T = len(idx); exit_shift = 1 + HOLD
    state_rows=[]; all_rows=[]

    next_signal_allowed = -1
    for i in range(T - exit_shift):
        if fold[i] not in DEV_FOLDS or fold[i + exit_shift] != fold[i]:
            continue
        vals = fm.iloc[i]
        beta_row = betas.iloc[i]
        eligible=[]
        for s in alpha_symbols:
            if not (np.isfinite(vals.get(s, np.nan)) and np.isfinite(beta_row.get(s, np.nan))):
                continue
            ent = data[s]["open"].iloc[i+1]; ex = data[s]["open"].iloc[i+exit_shift]
            if not (np.isfinite(ent) and np.isfinite(ex) and ent > 0 and ex > 0):
                continue
            eligible.append(s)
        btc_ent = data["BTC"]["open"].iloc[i+1]; btc_ex = data["BTC"]["open"].iloc[i+exit_shift]
        if len(eligible) < 2*K or not (np.isfinite(btc_ent) and np.isfinite(btc_ex) and btc_ent > 0 and btc_ex > 0):
            continue
        ranked = sorted(eligible, key=lambda s: (float(vals[s]), s))
        low = ranked[:K]; high = ranked[-K:]
        if set(low).intersection(high):
            continue
        w={s:0.0 for s in alpha_symbols};
        for s in low: w[s] = 0.5/K
        for s in high: w[s] = -0.5/K
        net_beta = sum(w[s] * float(beta_row[s]) for s in alpha_symbols)
        btc_w = -net_beta
        gross_norm = sum(abs(x) for x in w.values()) + abs(btc_w)
        if not np.isfinite(gross_norm) or gross_norm <= 0:
            continue
        w={s:x/gross_norm for s,x in w.items()}; btc_w /= gross_norm
        score = float(vals[high].mean() - vals[low].mean())
        price=0.0; funding=0.0; contrib={}
        valid=True
        for s, ws in w.items():
            if ws == 0: continue
            ent=float(data[s]["open"].iloc[i+1]); ex=float(data[s]["open"].iloc[i+exit_shift])
            fret=(ex/ent-1.0)*1e4
            fsum=float(data[s]["fcum"].iloc[i+exit_shift]-data[s]["fcum"].iloc[i+1])*1e4
            c=ws*fret-ws*fsum
            if not np.isfinite(c): valid=False; break
            price += ws*fret; funding += -ws*fsum; contrib[s]=c
        if not valid: continue
        btc_fret=(float(btc_ex)/float(btc_ent)-1.0)*1e4
        btc_fsum=float(data["BTC"]["fcum"].iloc[i+exit_shift]-data["BTC"]["fcum"].iloc[i+1])*1e4
        btc_contrib=btc_w*btc_fret-btc_w*btc_fsum
        if not np.isfinite(btc_contrib): continue
        price += btc_w*btc_fret; funding += -btc_w*btc_fsum; contrib["BTC"]=btc_contrib
        gross=price+funding
        state_rows.append((i,int(fold[i]),score,funding))
        if i >= next_signal_allowed:
            all_rows.append({"i":i,"timestamp":str(idx[i]),"fold":int(fold[i]),"score":score,"funding_target":funding,
                             "gross":gross,"low":low,"high":high,"btc_weight":btc_w,"contrib":contrib})
            next_signal_allowed=i+exit_shift

    sr=pd.DataFrame(state_rows,columns=["i","fold","score","target"])
    fold_rhos=[]
    if len(sr):
        for fid,g in sr.groupby("fold"):
            r=rho(g.score,g.target)
            if np.isfinite(r): fold_rhos.append((int(fid),r))
    tr=pd.DataFrame([{k:v for k,v in row.items() if k != "contrib"} for row in all_rows])
    out={"nsett":nsett,"k":K,"hold_hours":HOLD,"alpha_symbols":alpha_symbols,"symbol_count":len(alpha_symbols),
         "state_observations":len(sr),"state_folds":len(fold_rhos),
         "state_median_spearman":float(np.median([x[1] for x in fold_rhos])) if fold_rhos else np.nan,
         "state_positive_fold_fraction":float(np.mean([x[1]>0 for x in fold_rhos])) if fold_rhos else 0.0,
         "state_fold_rhos":[{"fold":f,"rho":r} for f,r in fold_rhos],"trades":len(tr)}
    for name,cost in COSTS.items():
        if len(tr):
            net=tr.gross.astype(float)-cost
            tmp=tr.assign(net=net)
            fexp=tmp.groupby("fold").net.mean(); fpf=tmp.groupby("fold").net.apply(pf)
            out[f"{name}_median_fold_net_bps"]=float(fexp.median())
            out[f"{name}_median_fold_pf"]=float(fpf.median())
            out[f"{name}_positive_fold_fraction"]=float((fexp>0).mean())
            out[f"{name}_mean_net_bps"]=float(net.mean())
            if name=="primary":
                out["primary_fold_means"]={str(int(k)):float(v) for k,v in fexp.items()}
        else:
            out[f"{name}_median_fold_net_bps"]=np.nan; out[f"{name}_median_fold_pf"]=np.nan
            out[f"{name}_positive_fold_fraction"]=0.0; out[f"{name}_mean_net_bps"]=np.nan
    out["reversed_primary_mean_net_bps"]=float((-tr.gross.astype(float)-COSTS["primary"]).mean()) if len(tr) else np.nan
    out["state_pass"]=bool(out["state_folds"]>=10 and out["state_median_spearman"]>0 and out["state_positive_fold_fraction"]>=0.60)
    out["basic_economic_pass"]=bool(out["state_pass"] and len(tr)>=40 and out["primary_median_fold_net_bps"]>0 and
                                    out["primary_median_fold_pf"]>1 and out["primary_positive_fold_fraction"]>=0.60 and
                                    out["high_median_fold_net_bps"]>=0 and out["primary_mean_net_bps"]>out["reversed_primary_mean_net_bps"])
    if len(tr):
        strongest=max(out["primary_fold_means"],key=lambda k:out["primary_fold_means"][k])
        remain=[v for k,v in out["primary_fold_means"].items() if k != strongest]
        out["strongest_fold"] = int(strongest)
        out["positive_fold_fraction_without_strongest"] = float(np.mean(np.array(remain)>0)) if remain else 0.0
    else:
        out["strongest_fold"]=None; out["positive_fold_fraction_without_strongest"]=0.0
    sums={s:0.0 for s in ["BTC"]+alpha_symbols}
    counts={s:0 for s in ["BTC"]+alpha_symbols}
    for row in all_rows:
        for s,c in row["contrib"].items(): sums[s]+=float(c); counts[s]+=1
    out["symbol_gross_contribution_bps"]={s:{"sum":sums[s],"active_trades":counts[s]} for s in sums if counts[s]}
    if include_trade_details:
        out["trade_rows"]=all_rows
    return clean(out)


def loo_diagnostics(data_dir: Path, symbols: list[str], nsett: int) -> dict:
    rows=[]
    for removed in symbols:
        keep=[s for s in symbols if s != removed]
        r=evaluate(data_dir,keep,nsett,include_trade_details=False)
        rows.append({"removed":removed,"trades":r["trades"],"primary_median_fold_net_bps":r["primary_median_fold_net_bps"],
                     "primary_positive_fold_fraction":r["primary_positive_fold_fraction"],"state_median_spearman":r["state_median_spearman"]})
    finite=[x for x in rows if x["primary_median_fold_net_bps"] is not None]
    frac=float(np.mean([x["primary_median_fold_net_bps"]>0 for x in finite])) if finite else 0.0
    return {"rows":rows,"positive_median_expectancy_fraction":frac}


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--config",required=True); ap.add_argument("--data-dir",required=True); ap.add_argument("--output",required=True)
    args=ap.parse_args(); cfg=json.loads(Path(args.config).read_text()); data_dir=Path(args.data_dir)
    manifest=json.loads((data_dir/"manifest.json").read_text())
    primary=list(manifest["primary_expansion_panel"])
    if len(primary) < int(cfg["universe_construction"]["minimum_primary_panel_size"]):
        raise SystemExit("primary panel below frozen minimum")
    primary_results=[]
    for nsett in [3,5]:
        base=evaluate(data_dir,primary,nsett,include_trade_details=True)
        loo=loo_diagnostics(data_dir,primary,nsett)
        base["leave_one_symbol_out"]=loo
        base["generalization_pass"]=bool(base["basic_economic_pass"] and
            base["positive_fold_fraction_without_strongest"]>=0.60 and
            loo["positive_median_expectancy_fraction"]>=0.80)
        primary_results.append(base)
    original_available=[s for s in ORIGINAL_NON_BTC if (data_dir/f"{s}_futures_1h.csv").exists() and (data_dir/f"{s}_funding.csv").exists()]
    combined=list(dict.fromkeys(primary+original_available))
    combined_results=[evaluate(data_dir,combined,n,include_trade_details=False) for n in [3,5]]
    same_state_sign=all((r["state_median_spearman"] is not None and r["state_median_spearman"]>0) for r in primary_results)
    final_pass=bool(same_state_sign and all(r["generalization_pass"] for r in primary_results))
    out={"schema_version":1,"protocol":cfg["protocol_name"],"evidence_class":"retrospective_cross_symbol_generalization_not_oos",
         "manifest_primary_panel":primary,"primary_results":primary_results,"combined_diagnostic_symbols":combined,
         "combined_diagnostic_results":combined_results,"both_frozen_cells_same_positive_state_sign":same_state_sign,
         "generalization_pass":final_pass,"parent_holdout_opened":False,"leverage_tested":False,
         "claims":{"verified_oos":False,"profitable_edge_established":False,"live_enabled":False}}
    Path(args.output).parent.mkdir(parents=True,exist_ok=True); Path(args.output).write_text(json.dumps(clean(out),indent=2))
    print(json.dumps({"panel":primary,"results":[{"nsett":r["nsett"],"state":r["state_median_spearman"],"net":r["primary_median_fold_net_bps"],"pf":r["primary_median_fold_pf"],"posfold":r["primary_positive_fold_fraction"],"loo":r["leave_one_symbol_out"]["positive_median_expectancy_fraction"],"pass":r["generalization_pass"]} for r in primary_results],"generalization_pass":final_pass},indent=2))


if __name__ == "__main__":
    main()
