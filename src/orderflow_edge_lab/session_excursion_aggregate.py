from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from orderflow_edge_lab.session_metrics import _parse_timestamp, session_regime


class SessionExcursionAggregateError(ValueError):
    pass


def _quantile(values:list[float], q:float)->float|None:
    if not values:
        return None
    xs=sorted(values)
    pos=(len(xs)-1)*q
    lo=int(pos)
    hi=min(lo+1,len(xs)-1)
    frac=pos-lo
    return xs[lo]*(1-frac)+xs[hi]*frac


def _summary(rows:list[dict[str,Any]])->dict[str,Any]:
    if not rows:
        return {"observations":0}
    mfe=[float(r["mfe_bps"]) for r in rows]
    mae=[float(r["mae_bps"]) for r in rows]
    gross=[float(r["fixed_horizon_gross_bps"]) for r in rows]
    net=[float(r["fixed_horizon_net_bps"]) for r in rows]
    batches={str(r["batch_id"]) for r in rows}
    return {
        "observations":len(rows),
        "independent_batches":len(batches),
        "mfe_mean_bps":statistics.fmean(mfe),
        "mfe_median_bps":statistics.median(mfe),
        "mfe_p75_bps":_quantile(mfe,0.75),
        "mfe_p90_bps":_quantile(mfe,0.90),
        "mfe_p95_bps":_quantile(mfe,0.95),
        "mae_mean_bps":statistics.fmean(mae),
        "mae_median_bps":statistics.median(mae),
        "mae_p75_bps":_quantile(mae,0.75),
        "mfe_ge_10_rate":sum(v>=10 for v in mfe)/len(mfe),
        "mfe_ge_20_rate":sum(v>=20 for v in mfe)/len(mfe),
        "mfe_ge_30_rate":sum(v>=30 for v in mfe)/len(mfe),
        "mae_lt_10_rate":sum(v<10 for v in mae)/len(mae),
        "fixed_horizon_gross_mean_bps":statistics.fmean(gross),
        "fixed_horizon_net_mean_bps":statistics.fmean(net),
        "fixed_horizon_cumulative_net_bps":sum(net),
        "sample_warning":len(rows)<20 or len(batches)<3,
    }


def aggregate_session_excursions(
    history_dir:str|Path,
    *,
    horizon_ms:int=30000,
    fee_bps:float=4.0,
    rr_target:float=3.0,
    risk_fraction:float=0.0025,
)->dict[str,Any]:
    root=Path(history_dir)
    if not root.exists():
        raise SessionExcursionAggregateError(f"history directory not found: {root}")

    joined:list[dict[str,Any]]=[]
    batch_dirs=sorted({p.parent for p in root.rglob("conditions.json")})
    for batch_dir in batch_dirs:
        cp=batch_dir/"conditions.json"
        sp=batch_dir/"stop_risk.json"
        if not sp.exists():
            continue
        conditions=json.loads(cp.read_text(encoding="utf-8"))
        stop=json.loads(sp.read_text(encoding="utf-8"))
        cmap:dict[tuple[str,int],dict[str,Any]]={}
        for row in conditions.get("enriched_observations",[]):
            if not isinstance(row,dict):
                continue
            if int(row.get("horizon_ms",-1))!=horizon_ms:
                continue
            if float(row.get("fee_bps_round_trip",-1))!=fee_bps:
                continue
            if row.get("stream","original")!="original":
                continue
            key=(str(row.get("family")),int(row.get("signal_observed_at_ns")))
            cmap[key]=row

        seen:set[tuple[str,int]]=set()
        for trade in stop.get("trades",[]):
            if not isinstance(trade,dict) or trade.get("stream")!="original":
                continue
            if float(trade.get("rr_target",-1))!=rr_target:
                continue
            if float(trade.get("requested_risk_fraction",-1))!=risk_fraction:
                continue
            if float(trade.get("fee_bps_round_trip",-1))!=fee_bps:
                continue
            key=(str(trade.get("family")),int(trade.get("signal_observed_at_ns")))
            if key in seen:
                continue
            seen.add(key)
            cond=cmap.get(key)
            if cond is None:
                continue
            ns=key[1]
            dt=_parse_timestamp(ns,"signal_observed_at_ns")
            c=dict(cond.get("conditions") or {})
            regime=c.get("trading_session_regime") or session_regime(dt)
            joined.append({
                "batch_id":cond.get("batch_id",batch_dir.name),
                "family":key[0],
                "signal_observed_at_ns":ns,
                "session_regime":regime,
                "btc_flow_alignment":c.get("btc_flow_alignment"),
                "signal_strength_multiple":c.get("signal_strength_multiple"),
                "spread_bucket":c.get("spread_bps"),
                "range_to_spread_15s":c.get("range_to_spread_15s"),
                "activity_bucket":c.get("rolling_trade_count_10s"),
                "mfe_bps":float(trade["mfe_bps"]),
                "mae_bps":float(trade["mae_bps"]),
                "risk_exit_status":trade.get("status"),
                "fixed_horizon_gross_bps":float(cond["gross_bps"]),
                "fixed_horizon_net_bps":float(cond["net_bps"]),
            })

    if not joined:
        raise SessionExcursionAggregateError("no joinable excursion observations")

    by_session:dict[tuple[str,str],list[dict[str,Any]]]=defaultdict(list)
    by_context:dict[tuple[str,str,str,str],list[dict[str,Any]]]=defaultdict(list)
    by_movement_context:dict[tuple[str,str,str,str,str],list[dict[str,Any]]]=defaultdict(list)
    for row in joined:
        by_session[(row["family"],row["session_regime"])].append(row)
        by_context[(
            row["family"],
            row["session_regime"],
            str(row["btc_flow_alignment"]),
            str(row["signal_strength_multiple"]),
        )].append(row)
        by_movement_context[(
            row["family"],
            row["session_regime"],
            str(row["spread_bucket"]),
            str(row["range_to_spread_15s"]),
            str(row["btc_flow_alignment"]),
        )].append(row)

    session_rows=[]
    for (family,regime),rows in sorted(by_session.items()):
        session_rows.append({"family":family,"session_regime":regime,**_summary(rows)})

    context_rows=[]
    for (family,regime,btc,strength),rows in sorted(by_context.items()):
        if len(rows)<10:
            continue
        context_rows.append({
            "family":family,
            "session_regime":regime,
            "btc_flow_alignment":btc,
            "signal_strength_multiple":strength,
            **_summary(rows),
        })

    movement_context_rows=[]
    for (family,regime,spread_bucket,range_bucket,btc),rows in sorted(by_movement_context.items()):
        if len(rows)<10:
            continue
        movement_context_rows.append({
            "family":family,
            "session_regime":regime,
            "spread_bucket":spread_bucket,
            "range_to_spread_15s":range_bucket,
            "btc_flow_alignment":btc,
            **_summary(rows),
        })

    return {
        "schema_version":1,
        "analysis":"session_conditioned_excursion_aggregate",
        "risk_path_proxy":{
            "rr_target":rr_target,
            "requested_risk_fraction":risk_fraction,
            "fee_bps_round_trip":fee_bps,
            "fixed_horizon_ms":horizon_ms,
            "note":"MFE/MAE come from the frozen stop-risk path and can terminate at stop/target/time exit; they are not unconstrained full-horizon extrema.",
        },
        "joined_observations":len(joined),
        "batch_directories":len(batch_dirs),
        "by_family_session":session_rows,
        "by_family_session_btc_strength":context_rows,
        "by_family_session_spread_range_btc":movement_context_rows,
        "claims":{
            "exploratory_only":True,
            "mean_mfe_alone_is_not_sufficient":True,
            "inspect_median_and_quantiles":True,
            "session_filter_authorized":False,
        },
    }
