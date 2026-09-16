from __future__ import annotations

import argparse, hashlib, json, os
from pathlib import Path
import numpy as np
import pandas as pd

from orderflow_edge_lab.basis_convergence import fetch_mexc_funding_history
from orderflow_edge_lab.discovery_v2_sprint1 import VariantRun
from orderflow_edge_lab.discovery_v2_sprint11 import (
    selective_trend_acceleration_5d,
    selective_low_skew_90d,
    selective_funding_carry_14d,
    evaluate_selective_family,
)
from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines

FREEZE_COMMIT="c48623ce31bc1f5032635049f0a69f457e55af82"


def _load(path): return json.loads(Path(path).read_text())
def _safe(v):
    if isinstance(v,dict): return {str(k):_safe(x) for k,x in v.items()}
    if isinstance(v,(list,tuple)): return [_safe(x) for x in v]
    if isinstance(v,np.integer): return int(v)
    if isinstance(v,np.floating): v=float(v)
    if isinstance(v,float) and (np.isnan(v) or np.isinf(v)): return None
    if isinstance(v,pd.Timestamp): return v.isoformat()
    return v

def _sha(path):
    h=hashlib.sha256(); h.update(Path(path).read_bytes()); return h.hexdigest()

def _write(df,path):
    path.parent.mkdir(parents=True,exist_ok=True); df.sort_index().to_csv(path,index_label="timestamp")
    return {"path":str(path),"sha256":_sha(path),"rows":len(df),"start":df.index.min().isoformat(),"end":df.index.max().isoformat()}

def _fetch(protocol,out):
    cfg=protocol["data"]; daily={}; funding={}; files={}
    for symbol in cfg["symbols"]:
        d=fetch_mexc_futures_klines(symbol,"1d",cfg["development_start_utc"],cfg["development_end_utc_exclusive"],request_pause_seconds=0.10)
        f=fetch_mexc_funding_history(symbol,cfg["development_start_utc"],cfg["development_end_utc_exclusive"],page_size=1000,max_pages=20)
        if d.empty or f.empty or len(d)<120 or len(f)<100: raise RuntimeError(f"{symbol}: incomplete history")
        daily[symbol],funding[symbol]=d,f
        files[f"{symbol}:1d"]=_write(d,out/"daily"/f"{symbol}_1d.csv")
        files[f"{symbol}:funding"]=_write(f,out/"funding"/f"{symbol}_funding.csv")
    manifest={"source":"MEXC public REST","files":files,"no_2025_data_for_discovery":cfg["no_2025_data_for_discovery"],"survivorship_warning":cfg["survivorship_warning"]}
    p=out/"dataset_manifest.json"; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(_safe(manifest),indent=2,sort_keys=True)); manifest["manifest_sha256"]=_sha(p)
    return daily,funding,manifest

def _dense(run,symbols):
    x=run.contributions.copy()
    if x.empty: x=pd.DataFrame(columns=["timestamp","symbol","net_contribution_bps"])
    x["timestamp"]=pd.to_datetime(x["timestamp"],utc=True)
    keyed={(pd.Timestamp(r.timestamp),str(r.symbol)):float(r.net_contribution_bps) for r in x.itertuples(index=False)}
    rows=[{"timestamp":t,"symbol":s,"net_contribution_bps":keyed.get((pd.Timestamp(t),s),0.0)} for t in run.observations.index for s in symbols]
    return VariantRun(run.observations.copy(),pd.DataFrame(rows))

def _persist(family,candidate,reversed_run,parent,out):
    runs={"candidate":candidate,"reversed_same_gate":reversed_run,"ungated_parent":parent}
    for name,run in runs.items():
        p=out/"series"/family/name; p.mkdir(parents=True,exist_ok=True)
        run.observations.to_csv(p/"observations.csv",index_label="timestamp")
        run.contributions.to_csv(p/"symbol_contributions.csv",index=False)

def run(protocol,evaluation,out):
    out.mkdir(parents=True,exist_ok=True)
    daily,funding,manifest=_fetch(protocol,out/"data")
    symbols=list(protocol["data"]["symbols"])
    gate_cfg=protocol["opportunity_gate"]
    eval_gate=protocol["d0_research_candidate_gate"]
    cost=float(protocol["execution"]["transaction_cost_bps_per_side_on_actual_turnover"])
    reports={}
    specs=[
        ("selective_trend_acceleration_5d",selective_trend_acceleration_5d,"dv2_selective_trend_acceleration_5d_v1"),
        ("selective_low_skew_90d",selective_low_skew_90d,"dv2_selective_low_skew_90d_v1"),
        ("selective_funding_carry_14d",selective_funding_carry_14d,"dv2_selective_funding_carry_14d_v1"),
    ]
    for family,fn,candidate_id in specs:
        warmup=int(protocol["families"][family]["score_warmup_days"])
        kw=dict(
            daily_frames=daily,
            symbols=symbols,
            funding_frames=funding,
            quality_history_days=int(gate_cfg["history_days"]),
            quality_percentile=float(gate_cfg["quality_percentile"]),
            common_warmup_days=warmup,
            side_cost_bps=cost,
        )
        candidate=_dense(fn(**kw,reverse=False,selective=True),symbols)
        reversed_run=_dense(fn(**kw,reverse=True,selective=True),symbols)
        parent=_dense(fn(**kw,reverse=False,selective=False),symbols)
        reports[family]=evaluate_selective_family(candidate,reversed_run,parent,evaluation_config=evaluation,gate=eval_gate,candidate_id=candidate_id)
        _persist(family,candidate,reversed_run,parent,out)
    return {
        "protocol":protocol["protocol"],
        "protocol_freeze_commit":FREEZE_COMMIT,
        "execution_commit":os.getenv("GITHUB_SHA"),
        "independence_level":"D0_SELECTIVE_DISCOVERY",
        "dataset_manifest":manifest,
        "families":reports,
        "claims":{"persistent_edge_established":False,"live_execution_supported":False,"leverage_supported":False},
    }

def main():
    p=argparse.ArgumentParser(); p.add_argument("--protocol",default="config/discovery_v2_sprint11_selective_v1.json"); p.add_argument("--evaluation",default="config/discovery_v2_evaluation_v1.json"); p.add_argument("--output-dir",default="research/discovery_v2/sprint11/results"); a=p.parse_args()
    out=Path(a.output_dir); report=_safe(run(_load(a.protocol),_load(a.evaluation),out)); (out/"sprint11_report.json").write_text(json.dumps(report,indent=2,sort_keys=True)); print(json.dumps({k:v["state"] for k,v in report["families"].items()},indent=2,sort_keys=True))

if __name__=="__main__": main()
