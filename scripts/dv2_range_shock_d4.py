from __future__ import annotations

import argparse, json
from pathlib import Path
from typing import Any
import numpy as np, pandas as pd

from orderflow_edge_lab.basis_convergence import fetch_mexc_funding_history
from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines
from orderflow_edge_lab.range_shock_momentum_forward import simulate_forward, summarize

def _safe(v:Any):
    if isinstance(v,dict): return {str(k):_safe(x) for k,x in v.items()}
    if isinstance(v,(list,tuple)): return [_safe(x) for x in v]
    if isinstance(v,np.integer): return int(v)
    if isinstance(v,np.floating): v=float(v)
    if isinstance(v,float) and (np.isnan(v) or np.isinf(v)): return None
    if isinstance(v,pd.Timestamp): return v.isoformat()
    return v

def main():
    p=argparse.ArgumentParser(); p.add_argument("--protocol",default="config/dv2_liquidity_range_shock_momentum_30d_d4_v1.json"); p.add_argument("--candidate",default="config/dv2_liquidity_range_shock_momentum_30d_v1.json"); p.add_argument("--output-dir",default="research/discovery_v2/range_shock_momentum_30d/d4_shadow"); a=p.parse_args()
    protocol=json.loads(Path(a.protocol).read_text()); candidate=json.loads(Path(a.candidate).read_text()); assert protocol["candidate_id"]==candidate["candidate_id"]
    asof=pd.Timestamp.now(tz="UTC"); fetch_end=asof.normalize()+pd.Timedelta(days=1); symbols=list(protocol["data"]["symbols"]); prices={}; funding={}
    for s in symbols:
        prices[s]=fetch_mexc_futures_klines(s,"1d",protocol["data"]["history_start_utc"],fetch_end.isoformat(),request_pause_seconds=.05)
        funding[s]=fetch_mexc_funding_history(s,protocol["data"]["history_start_utc"],fetch_end.isoformat(),page_size=1000,max_pages=20)
    kw=dict(frames=prices,funding_frames=funding,symbols=symbols,range_baseline_days=int(protocol["rule"]["range_baseline_days"]),forward_start=pd.Timestamp(protocol["forward_start_utc"]),asof=asof,side_cost_bps=float(protocol["rule"]["transaction_cost_bps_per_side_on_actual_turnover"]))
    exact=simulate_forward(**kw,reverse=False); control=simulate_forward(**kw,reverse=True); es=summarize(exact); cs=summarize(control); out=Path(a.output_dir); out.mkdir(parents=True,exist_ok=True)
    if not exact["observations"].empty:
        exact["observations"].to_csv(out/"observations.csv",index_label="timestamp"); exact["contributions"].to_csv(out/"symbol_contributions.csv",index=False); exact["weights"].to_csv(out/"weights.csv",index_label="timestamp")
    start=pd.Timestamp(protocol["forward_start_utc"]); before=asof<start
    if before and es["completed_periods"]!=0: raise RuntimeError("pre-start D4 PnL detected")
    if es["completed_periods"] and pd.Timestamp(es["start"])<start: raise RuntimeError("D4 starts before forward boundary")
    minimum=int(protocol["review_after_completed_portfolio_periods"])
    report={"shadow_id":protocol["shadow_id"],"candidate_id":candidate["candidate_id"],"asof_utc":asof.isoformat(),"forward_start_utc":protocol["forward_start_utc"],"state":"EVIDENCE_ACCUMULATING" if es["completed_periods"] else "PROSPECTIVE_SHADOW","exact_candidate":es,"principal_reversed_control":cs,"review_minimum_completed_periods":minimum,"review_minimum_met":es["completed_periods"]>=minimum,"boundary_checks":{"flat_at_forward_start":True,"no_pre_start_pnl":es["completed_periods"]==0 if before else (es["start"] is None or pd.Timestamp(es["start"])>=start),"no_artificial_terminal_liquidation":True,"completed_periods_only":True},"claims":{"paper_shadow_only":True,"persistent_edge_established":False,"live_eligible":False,"leverage_supported":False,"retuning_allowed":False,"no_pre_start_backfill":True}}
    report=_safe(report); (out/"D4_REPORT.json").write_text(json.dumps(report,indent=2,sort_keys=True)); print(json.dumps({"asof":report["asof_utc"],"completed":es["completed_periods"],"pnl_per_1000":es["pnl_per_1000"],"hash":es["observations_sha256"],"open":es["open_position"]},indent=2,sort_keys=True))
if __name__=="__main__": main()
