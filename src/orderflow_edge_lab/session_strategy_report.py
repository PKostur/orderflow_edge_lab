from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping


class SessionStrategyReportError(ValueError):
    pass


def _pf(values: list[float]) -> float | str | None:
    pos=sum(v for v in values if v>0)
    neg=-sum(v for v in values if v<0)
    if neg>0:
        return pos/neg
    return "INF" if pos>0 else None


def _max_dd(values: list[float]) -> float:
    cum=0.0
    peak=0.0
    worst=0.0
    for v in values:
        cum+=v
        peak=max(peak,cum)
        worst=min(worst,cum-peak)
    return worst


def _summ(rows:list[dict[str,Any]])->dict[str,Any]:
    rows=sorted(rows,key=lambda r:int(r["signal_observed_at_ns"]))
    vals=[float(r["net_bps"]) for r in rows]
    if not vals:
        return {"observations":0}
    wins=[v for v in vals if v>0]
    losses=[v for v in vals if v<=0]
    by_batch:dict[str,list[float]]=defaultdict(list)
    for r in rows:
        by_batch[str(r.get("batch_id"))].append(float(r["net_bps"]))
    batch_means={k:statistics.fmean(v) for k,v in by_batch.items()}
    pos_total=sum(wins)
    ranked=sorted(wins,reverse=True)
    return {
        "observations":len(vals),
        "independent_batches":len(by_batch),
        "cumulative_net_bps":sum(vals),
        "net_mean_bps":statistics.fmean(vals),
        "net_median_bps":statistics.median(vals),
        "win_rate":len(wins)/len(vals),
        "average_win_bps":statistics.fmean(wins) if wins else None,
        "average_loss_bps":statistics.fmean(losses) if losses else None,
        "profit_factor":_pf(vals),
        "max_drawdown_bps":_max_dd(vals),
        "positive_batch_fraction":sum(x>0 for x in batch_means.values())/len(batch_means) if batch_means else None,
        "largest_positive_trade_share":ranked[0]/pos_total if pos_total>0 and ranked else None,
        "top_three_positive_trade_share":sum(ranked[:3])/pos_total if pos_total>0 else None,
        "average_spread_bps":statistics.fmean(float(r["spread_bps"]) for r in rows if r.get("spread_bps") is not None) if any(r.get("spread_bps") is not None for r in rows) else None,
        "average_local_range_15s_bps":statistics.fmean(float(r["local_range_15s_bps"]) for r in rows if r.get("local_range_15s_bps") is not None) if any(r.get("local_range_15s_bps") is not None for r in rows) else None,
        "average_signal_strength_multiple":statistics.fmean(float(r["signal_strength_multiple"]) for r in rows if r.get("signal_strength_multiple") is not None) if any(r.get("signal_strength_multiple") is not None for r in rows) else None,
    }


def build_session_strategy_report(condition_aggregate:Mapping[str,Any])->dict[str,Any]:
    if condition_aggregate.get("experiment")!="multi_batch_market_condition_aggregate":
        raise SessionStrategyReportError("expected multi_batch_market_condition_aggregate")
    obs=[dict(r) for r in condition_aggregate.get("enriched_observations",[]) if isinstance(r,Mapping)]
    if not obs:
        raise SessionStrategyReportError("no enriched observations")

    baselines:dict[tuple[str,int,float],list[dict[str,Any]]]=defaultdict(list)
    groups:dict[tuple[str,int,float,str],list[dict[str,Any]]]=defaultdict(list)
    for r in obs:
        family=str(r["family"]); horizon=int(r["horizon_ms"]); fee=float(r["fee_bps_round_trip"])
        baselines[(family,horizon,fee)].append(r)
        regime=(r.get("conditions") or {}).get("trading_session_regime")
        if regime is not None:
            groups[(family,horizon,fee,str(regime))].append(r)

    rows=[]
    for (family,horizon,fee,regime),xs in sorted(groups.items()):
        base=_summ(baselines[(family,horizon,fee)])
        s=_summ(xs)
        rows.append({
            "family":family,
            "horizon_ms":horizon,
            "fee_bps_round_trip":fee,
            "session_regime":regime,
            **s,
            "baseline_observations":base["observations"],
            "baseline_net_mean_bps":base["net_mean_bps"],
            "baseline_win_rate":base["win_rate"],
            "baseline_profit_factor":base["profit_factor"],
            "net_mean_delta_vs_baseline":s["net_mean_bps"]-base["net_mean_bps"],
            "win_rate_delta_vs_baseline":s["win_rate"]-base["win_rate"],
            "sample_warning": s["observations"]<20 or s["independent_batches"]<3,
        })

    return {
        "schema_version":1,
        "analysis":"session_conditioned_strategy_economics",
        "symbol":condition_aggregate.get("symbol"),
        "context_symbol":condition_aggregate.get("context_symbol"),
        "rows":rows,
        "interpretation_rule":{
            "do_not_rank_on_endpoint_only":True,
            "inspect":["cumulative_net_bps","net_mean_bps","win_rate","average_win_bps","average_loss_bps","profit_factor","max_drawdown_bps","positive_batch_fraction","pnl_concentration"],
            "session_filter_requires_future_freeze":True,
        },
        "claims":{
            "exploratory_only":True,
            "session_filter_authorized":False,
            "live_order_transmission_supported":False,
        },
    }


def load_aggregate(path:str|Path)->dict[str,Any]:
    payload=json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload,dict):
        raise SessionStrategyReportError("aggregate must be an object")
    return payload
