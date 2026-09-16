from __future__ import annotations

import argparse, hashlib, json, os
from pathlib import Path
import numpy as np
import pandas as pd

from orderflow_edge_lab.basis_convergence import fetch_mexc_funding_history
from orderflow_edge_lab.discovery_v2_sprint1 import VariantRun
from orderflow_edge_lab.discovery_v2_sprint13 import PayoffMetaRun, evaluate_payoff_meta, run_payoff_meta
from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines

FREEZE_COMMIT="815df9b5c3acec3b66d7b145ac7a9fabdd0524a3"


def _load(p): return json.loads(Path(p).read_text())
def _safe(v):
    if isinstance(v,dict): return {str(k):_safe(x) for k,x in v.items()}
    if isinstance(v,(list,tuple)): return [_safe(x) for x in v]
    if isinstance(v,np.integer): return int(v)
    if isinstance(v,np.floating): v=float(v)
    if isinstance(v,float) and (np.isnan(v) or np.isinf(v)): return None
    if isinstance(v,pd.Timestamp): return v.isoformat()
    return v

def _sha(p):
    h=hashlib.sha256(); h.update(Path(p).read_bytes()); return h.hexdigest()

def _write(df,p):
    p.parent.mkdir(parents=True,exist_ok=True); df.sort_index().to_csv(p,index_label="timestamp")
    return {"path":str(p),"sha256":_sha(p),"rows":len(df),"start":df.index.min().isoformat(),"end":df.index.max().isoformat()}

def _fetch(protocol,out):
    cfg=protocol["data"]; daily={}; funding={}; files={}
    for s in cfg["symbols"]:
        d=fetch_mexc_futures_klines(s,"1d",cfg["development_start_utc"],cfg["development_end_utc_exclusive"],request_pause_seconds=0.10)
        f=fetch_mexc_funding_history(s,cfg["development_start_utc"],cfg["development_end_utc_exclusive"],page_size=1000,max_pages=20)
        if d.empty or f.empty or len(d)<120 or len(f)<100: raise RuntimeError(f"{s}: incomplete history")
        daily[s],funding[s]=d,f; files[f"{s}:1d"]=_write(d,out/"daily"/f"{s}_1d.csv"); files[f"{s}:funding"]=_write(f,out/"funding"/f"{s}_funding.csv")
    m={"source":"MEXC public REST","files":files,"no_2025_data_for_discovery":cfg["no_2025_data_for_discovery"],"survivorship_warning":cfg["survivorship_warning"]}
    p=out/"dataset_manifest.json"; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(_safe(m),indent=2,sort_keys=True)); m["manifest_sha256"]=_sha(p); return daily,funding,m

def _dense(run,symbols):
    x=run.contributions.copy()
    if x.empty: x=pd.DataFrame(columns=["timestamp","symbol","net_contribution_bps"])
    x["timestamp"]=pd.to_datetime(x["timestamp"],utc=True)
    keyed={(pd.Timestamp(r.timestamp),str(r.symbol)):float(r.net_contribution_bps) for r in x.itertuples(index=False)}
    rows=[{"timestamp":t,"symbol":s,"net_contribution_bps":keyed.get((pd.Timestamp(t),s),0.0)} for t in run.observations.index for s in symbols]
    return VariantRun(run.observations.copy(),pd.DataFrame(rows))

def _densify(meta,symbols):
    return PayoffMetaRun(_dense(meta.candidate,symbols),_dense(meta.reversed_same_decisions,symbols),_dense(meta.ungated_parent,symbols),_dense(meta.anti_meta,symbols),meta.predictions.copy())

def _persist(meta,out):
    for name,run in {"candidate":meta.candidate,"reversed_same_decisions":meta.reversed_same_decisions,"ungated_parent":meta.ungated_parent,"anti_meta_diagnostic":meta.anti_meta}.items():
        p=out/"series"/name; p.mkdir(parents=True,exist_ok=True); run.observations.to_csv(p/"observations.csv",index_label="timestamp"); run.contributions.to_csv(p/"symbol_contributions.csv",index=False)
    pred=meta.predictions.drop(columns=[c for c in ["target","reversed_target"] if c in meta.predictions.columns]).copy(); pred.to_csv(out/"series"/"payoff_predictions.csv",index=False)

def run(protocol,evaluation,out):
    out.mkdir(parents=True,exist_ok=True); daily,funding,manifest=_fetch(protocol,out/"data"); symbols=list(protocol["data"]["symbols"]); m=protocol["walk_forward_model"]; cost=float(protocol["execution"]["transaction_cost_bps_per_side_on_actual_turnover"])
    meta=run_payoff_meta(daily,symbols=symbols,funding_frames=funding,side_cost_bps=cost,ridge_alpha=float(m["ridge_alpha"]),training_window=int(m["training_window_prior_primary_setups"]),minimum_training=int(m["minimum_prior_primary_setups"]),trade_threshold_bps=float(m["trade_if_predicted_standalone_net_bps_greater_than"]))
    meta=_densify(meta,symbols); result=evaluate_payoff_meta(meta,evaluation_config=evaluation,gate=protocol["d0_research_candidate_gate"],candidate_id="dv2_payoff_meta_trend_acceleration_5d_v1"); _persist(meta,out)
    return {"protocol":protocol["protocol"],"protocol_freeze_commit":FREEZE_COMMIT,"execution_commit":os.getenv("GITHUB_SHA"),"independence_level":"D0_PAYOFF_META_DISCOVERY","dataset_manifest":manifest,"result":result,"claims":{"persistent_edge_established":False,"live_execution_supported":False,"leverage_supported":False}}

def main():
    p=argparse.ArgumentParser(); p.add_argument("--protocol",default="config/discovery_v2_sprint13_payoff_meta_v1.json"); p.add_argument("--evaluation",default="config/discovery_v2_evaluation_v1.json"); p.add_argument("--output-dir",default="research/discovery_v2/sprint13/results"); a=p.parse_args(); out=Path(a.output_dir); r=_safe(run(_load(a.protocol),_load(a.evaluation),out)); (out/"sprint13_report.json").write_text(json.dumps(r,indent=2,sort_keys=True)); print(json.dumps({"state":r["result"]["state"]},indent=2))
if __name__=="__main__": main()
