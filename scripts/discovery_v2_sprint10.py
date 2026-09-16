from __future__ import annotations

import argparse, hashlib, json, os
from pathlib import Path
import numpy as np
import pandas as pd

from orderflow_edge_lab.basis_convergence import fetch_mexc_funding_history
from orderflow_edge_lab.discovery_v2_sprint1 import VariantRun
from orderflow_edge_lab.discovery_v2_sprint10 import historical_max_return_momentum,historical_skewness_premium,historical_kurtosis_premium,evaluate_sprint10_family
from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines

FREEZE_COMMIT="715c8ebe5dab957e4dd6bfad7b6fb9931cf47c42"

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
    p.parent.mkdir(parents=True,exist_ok=True); df.sort_index().to_csv(p,index_label="timestamp"); return {"path":str(p),"sha256":_sha(p),"rows":len(df),"start":df.index.min().isoformat(),"end":df.index.max().isoformat()}
def _fetch(protocol,out):
    cfg=protocol["data"]; daily={}; funding={}; files={}
    for s in cfg["symbols"]:
        d=fetch_mexc_futures_klines(s,"1d",cfg["development_start_utc"],cfg["development_end_utc_exclusive"],request_pause_seconds=0.10)
        f=fetch_mexc_funding_history(s,cfg["development_start_utc"],cfg["development_end_utc_exclusive"],page_size=1000,max_pages=20)
        if d.empty or f.empty or len(d)<120 or len(f)<100: raise RuntimeError(f"{s}: incomplete history")
        daily[s],funding[s]=d,f; files[f"{s}:1d"]=_write(d,out/"daily"/f"{s}_1d.csv"); files[f"{s}:funding"]=_write(f,out/"funding"/f"{s}_funding.csv")
    m={"source":"MEXC public REST","files":files,"no_2025_data_for_discovery":cfg["no_2025_data_for_discovery"],"survivorship_warning":cfg["survivorship_warning"]}; p=out/"dataset_manifest.json"; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(_safe(m),indent=2,sort_keys=True)); m["manifest_sha256"]=_sha(p); return daily,funding,m

def _dense(run,symbols):
    x=run.contributions.copy(); x["timestamp"]=pd.to_datetime(x["timestamp"],utc=True)
    keyed={(pd.Timestamp(r.timestamp),str(r.symbol)):float(r.net_contribution_bps) for r in x.itertuples(index=False)}
    rows=[{"timestamp":t,"symbol":s,"net_contribution_bps":keyed.get((pd.Timestamp(t),s),0.0)} for t in run.observations.index for s in symbols]
    return VariantRun(run.observations.copy(),pd.DataFrame(rows))
def _persist(family,variants,controls,out):
    for cat,runs in (("variants",variants),("controls",controls)):
        for rid,run in runs.items():
            p=out/"series"/family/cat/rid; p.mkdir(parents=True,exist_ok=True); run.observations.to_csv(p/"observations.csv",index_label="timestamp"); run.contributions.to_csv(p/"symbol_contributions.csv",index=False)
def _eval(v,c,o,e,g): return evaluate_sprint10_family(v,c,ordered_variant_ids=o,evaluation_config=e,principal_control_for_variant={x:f"reverse_{x}" for x in o},gate=g)

def run(protocol,evaluation,out):
    out.mkdir(parents=True,exist_ok=True); daily,funding,manifest=_fetch(protocol,out/"data"); symbols=list(protocol["data"]["symbols"]); warmup=int(protocol["execution"]["common_comparison_warmup_days"]); cost=float(protocol["execution"]["transaction_cost_bps_per_side_on_actual_turnover"]); gate=protocol["family_falsification_gate"]; reports={}
    specs=[
      ("historical_max_return_momentum","lookback_days_variants","max",historical_max_return_momentum),
      ("historical_skewness_premium","lookback_days_variants","skew",historical_skewness_premium),
      ("historical_kurtosis_premium","lookback_days_variants","kurt",historical_kurtosis_premium),
    ]
    for family,key,prefix,fn in specs:
        cfg=protocol["families"][family]; variants={}; controls={}; ordered=[]
        for n in cfg[key]:
            vid=f"{prefix}_{int(n)}d"; ordered.append(vid); kw=dict(daily_frames=daily,symbols=symbols,funding_frames=funding,lookback_days=int(n),common_warmup_days=warmup,side_cost_bps=cost)
            variants[vid]=_dense(fn(**kw,reverse=False),symbols); controls[f"reverse_{vid}"]=_dense(fn(**kw,reverse=True),symbols)
        reports[family]=_eval(variants,controls,ordered,evaluation,gate); _persist(family,variants,controls,out)
    return {"protocol":protocol["protocol"],"protocol_freeze_commit":FREEZE_COMMIT,"execution_commit":os.getenv("GITHUB_SHA"),"independence_level":"D0_LITERATURE_TRANSFER","dataset_manifest":manifest,"families":reports,"claims":{"persistent_edge_established":False,"live_execution_supported":False,"leverage_supported":False,"paper_replication_claimed":False}}

def main():
    p=argparse.ArgumentParser(); p.add_argument("--protocol",default="config/discovery_v2_sprint10_literature_v1.json"); p.add_argument("--evaluation",default="config/discovery_v2_evaluation_v1.json"); p.add_argument("--output-dir",default="research/discovery_v2/sprint10/results"); a=p.parse_args(); out=Path(a.output_dir); r=_safe(run(_load(a.protocol),_load(a.evaluation),out)); (out/"sprint10_report.json").write_text(json.dumps(r,indent=2,sort_keys=True)); print(json.dumps({k:v["state"] for k,v in r["families"].items()},indent=2,sort_keys=True))
if __name__=="__main__": main()
