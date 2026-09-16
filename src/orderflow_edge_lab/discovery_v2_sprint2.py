from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from orderflow_edge_lab.discovery_v2_sprint1 import (
    VariantRun,
    _period_return,
    _validate_price_frames,
    evaluate_family,
)


class DiscoveryV2Sprint2Error(ValueError):
    pass


def _rank(scores: pd.Series, *, long_high: bool) -> pd.Series:
    clean = pd.to_numeric(scores, errors="coerce").dropna().sort_values()
    if len(clean) < 6:
        raise DiscoveryV2Sprint2Error("at least six ranked symbols required")
    low, high = list(clean.index[:2]), list(clean.index[-2:])
    out = pd.Series(0.0, index=scores.index, dtype=float)
    if long_high:
        out.loc[high] = 0.25; out.loc[low] = -0.25
    else:
        out.loc[low] = 0.25; out.loc[high] = -0.25
    return out


def _simulate_signals(signals: Sequence[tuple[int, int, pd.Series]], opens: pd.DataFrame,
                      funding_frames: Mapping[str, pd.DataFrame] | None, *, side_cost_bps: float) -> VariantRun:
    rows: list[dict[str, Any]] = []; contributions: list[dict[str, Any]] = []
    previous = pd.Series(0.0, index=opens.columns, dtype=float)
    valid = [(a, b, w.reindex(opens.columns, fill_value=0.0)) for a, b, w in signals if 0 <= a < b < len(opens)]
    for j, (start_i, end_i, target) in enumerate(valid):
        start, end = opens.index[start_i], opens.index[end_i]
        gross, cost, legs = _period_return(target, previous, opens, start, end, funding_frames, side_cost_bps,
                                           force_liquidation=j == len(valid)-1)
        rows.append({"timestamp": start, "end_timestamp": end, "gross_return_bps": gross*10000.0,
                     "cost_bps": cost*10000.0, "net_return_bps": (gross-cost)*10000.0,
                     "active_gross": float(target.abs().sum())})
        contributions.extend({"timestamp": start, "symbol": s, "net_contribution_bps": v*10000.0} for s, v in legs.items())
        previous = target
    if not rows:
        raise DiscoveryV2Sprint2Error("no completed observations")
    return VariantRun(pd.DataFrame(rows).set_index("timestamp"), pd.DataFrame(contributions))


def same_weekday_seasonality(daily_frames: Mapping[str, pd.DataFrame], *, symbols: Sequence[str],
                             funding_frames: Mapping[str, pd.DataFrame] | None, lookback_weeks: int,
                             common_warmup_weeks: int, side_cost_bps: float, reverse: bool=False) -> VariantRun:
    opens, closes = _validate_price_frames(daily_frames, symbols); returns = closes.pct_change(); signals=[]
    earliest_i = int(common_warmup_weeks)*7
    for i in range(earliest_i, len(opens)-2):
        start_i, end_i = i+1, i+2; execution_weekday = opens.index[start_i].weekday()
        prior_idx = [k for k in range(1, i+1) if closes.index[k].weekday() == execution_weekday]
        if len(prior_idx) < int(lookback_weeks): continue
        scores = returns.iloc[prior_idx[-int(lookback_weeks):]].mean(axis=0)
        signals.append((start_i, end_i, _rank(scores, long_high=not reverse)))
    return _simulate_signals(signals, opens, funding_frames, side_cost_bps=side_cost_bps)


def low_idiosyncratic_volatility(daily_frames: Mapping[str, pd.DataFrame], *, symbols: Sequence[str],
                                 funding_frames: Mapping[str, pd.DataFrame] | None, lookback_days: int,
                                 common_warmup_days: int, side_cost_bps: float, reverse: bool=False) -> VariantRun:
    if "BTC_USDT" not in symbols: raise DiscoveryV2Sprint2Error("BTC_USDT factor required")
    opens, closes = _validate_price_frames(daily_frames, symbols); returns=closes.pct_change(); alts=[s for s in symbols if s!="BTC_USDT"]; signals=[]
    for i in range(int(common_warmup_days)+1, len(opens)-8, 7):
        x=returns["BTC_USDT"].iloc[i-int(lookback_days):i].to_numpy(dtype=float)
        if not np.isfinite(x).all(): continue
        xmat=np.column_stack([np.ones(len(x)),x]); scores=pd.Series(index=alts,dtype=float)
        for s in alts:
            y=returns[s].iloc[i-int(lookback_days):i].to_numpy(dtype=float)
            if not np.isfinite(y).all(): scores[s]=np.nan; continue
            coef,*_=np.linalg.lstsq(xmat,y,rcond=None); scores[s]=float(np.std(y-xmat@coef,ddof=1))
        target=_rank(scores,long_high=reverse).reindex(opens.columns,fill_value=0.0)
        signals.append((i+1,i+8,target))
    return _simulate_signals(signals,opens,funding_frames,side_cost_bps=side_cost_bps)


def _sample_skew(values: np.ndarray) -> float:
    v=np.asarray(values,dtype=float); v=v[np.isfinite(v)]; n=len(v)
    if n<3: return float("nan")
    mean=float(v.mean()); sd=float(v.std(ddof=1))
    if sd<=0: return 0.0
    return float((n/((n-1)*(n-2)))*np.sum(((v-mean)/sd)**3))


def intraday_skewness(daily_frames: Mapping[str,pd.DataFrame], four_hour_frames: Mapping[str,pd.DataFrame], *,
                      symbols: Sequence[str], funding_frames: Mapping[str,pd.DataFrame] | None,
                      lookback_days: int, common_warmup_days: int, side_cost_bps: float,
                      reverse: bool=False) -> VariantRun:
    opens,_=_validate_price_frames(daily_frames,symbols)
    four_closes=pd.concat({s:pd.to_numeric(four_hour_frames[s]["close"],errors="coerce") for s in symbols},axis=1,join="inner").dropna().sort_index()
    log_returns=np.log(four_closes).diff(); signals=[]
    for i in range(int(common_warmup_days),len(opens)-2):
        start_i,end_i=i+1,i+2; boundary=opens.index[start_i]; available_at=log_returns.index+pd.Timedelta(hours=4)
        recent=log_returns.loc[(available_at<=boundary)&(available_at>boundary-pd.Timedelta(days=int(lookback_days)))]
        if len(recent)<3: continue
        scores=recent.apply(lambda s:_sample_skew(s.to_numpy(dtype=float)),axis=0)
        signals.append((start_i,end_i,_rank(scores,long_high=reverse)))
    return _simulate_signals(signals,opens,funding_frames,side_cost_bps=side_cost_bps)


def evaluate_sprint2_family(variants: Mapping[str,VariantRun], controls: Mapping[str,VariantRun], *,
                            ordered_variant_ids: Sequence[str], evaluation_config: Mapping[str,Any],
                            principal_control_for_variant: Mapping[str,str], gate: Mapping[str,Any]) -> dict[str,Any]:
    base=evaluate_family(variants,controls,ordered_variant_ids=ordered_variant_ids,evaluation_config=evaluation_config,
                         principal_control_for_variant=principal_control_for_variant)
    neighborhood=list(base["stable_neighborhood"]); selected=None
    if len(neighborhood)>=int(gate["minimum_adjacent_variants_positive_at_1_5x_cost"]):
        positions=sorted(list(ordered_variant_ids).index(v) for v in neighborhood); selected=list(ordered_variant_ids)[positions[len(positions)//2]]
    cs=base["variant_summaries"].get(selected) if selected else None; cid=principal_control_for_variant.get(selected) if selected else None
    ctrl=base["control_summaries"].get(cid) if cid else None; advantage=float(cs["mean_net_bps"]-ctrl["mean_net_bps"]) if cs and ctrl else None
    checks={
        "baseline_positive_breadth":len(base["baseline_positive_variants"])>=int(gate["minimum_baseline_positive_variants"]),
        "adjacent_positive_at_1_5x":len(neighborhood)>=int(gate["minimum_adjacent_variants_positive_at_1_5x_cost"]),
        "selected_bootstrap_lower_positive":bool(cs and float(cs["bootstrap_lower_bps"])>0),
        "selected_beats_reversed_control_by_5bps":advantage is not None and advantage>=float(gate["minimum_candidate_minus_reversed_control_mean_bps"]),
        "selected_leave_one_symbol_out_positive":bool(cs and cs["minimum_leave_one_symbol_out_mean_bps"] is not None and float(cs["minimum_leave_one_symbol_out_mean_bps"])>float(gate["minimum_leave_one_symbol_out_mean_bps"])),
        "selected_best_symbol_share":bool(cs and cs["best_symbol_positive_pnl_share"] is not None and float(cs["best_symbol_positive_pnl_share"])<=float(gate["maximum_best_symbol_positive_pnl_share"])),
        "selected_best_month_share":bool(cs and cs["best_calendar_month_positive_pnl_share"] is not None and float(cs["best_calendar_month_positive_pnl_share"])<=float(gate["maximum_best_calendar_month_positive_pnl_share"])),
        "selected_top5_share":bool(cs and cs["top5_positive_period_share"] is not None and float(cs["top5_positive_period_share"])<=float(gate["maximum_top5_positive_period_share"])),
    }
    base["sprint2_selected_variant"]=selected if all(checks.values()) else None; base["sprint2_selected_control"]=cid
    base["sprint2_selected_advantage_bps"]=advantage; base["sprint2_hard_checks"]=checks
    base["state"]="REPLICATION_PENDING" if selected is not None and all(checks.values()) else "FALSIFIED"
    base["claims"]={"d0_result_establishes_edge":False,"live_eligible":False}
    return base
