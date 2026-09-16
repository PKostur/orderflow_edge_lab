from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from orderflow_edge_lab.discovery_v2_sprint1 import VariantRun, _validate_price_frames
from orderflow_edge_lab.discovery_v2_sprint2 import _rank, _simulate_signals, evaluate_sprint2_family


def _field(frames: Mapping[str, pd.DataFrame], symbols: Sequence[str], name: str, idx: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.concat({s: pd.to_numeric(frames[s][name], errors="coerce") for s in symbols}, axis=1, join="inner").sort_index().reindex(idx)


def wick_rejection_followthrough(daily_frames, *, symbols, funding_frames, lookback_days, common_warmup_days, side_cost_bps, reverse=False) -> VariantRun:
    opens, closes = _validate_price_frames(daily_frames, symbols)
    highs, lows = _field(daily_frames, symbols, "high", opens.index), _field(daily_frames, symbols, "low", opens.index)
    width = (highs-lows).replace(0.0, np.nan)
    lower = pd.DataFrame(np.minimum(opens, closes), index=opens.index, columns=opens.columns) - lows
    upper = highs - pd.DataFrame(np.maximum(opens, closes), index=opens.index, columns=opens.columns)
    daily_score = (lower-upper)/width
    signals=[]
    for i in range(int(common_warmup_days), len(opens)-2):
        scores=daily_score.iloc[i-int(lookback_days)+1:i+1].mean(axis=0).replace([np.inf,-np.inf],np.nan)
        if scores.notna().sum()<6: continue
        signals.append((i+1,i+2,_rank(scores,long_high=not bool(reverse)).reindex(opens.columns,fill_value=0.0)))
    return _simulate_signals(signals,opens,funding_frames,side_cost_bps=side_cost_bps)


def return_efficiency_continuation(daily_frames, *, symbols, funding_frames, lookback_days, common_warmup_days, side_cost_bps, reverse=False) -> VariantRun:
    opens, closes = _validate_price_frames(daily_frames, symbols); ret=closes.pct_change(); signals=[]
    for i in range(int(common_warmup_days),len(opens)-2):
        x=ret.iloc[i-int(lookback_days)+1:i+1]
        denom=x.abs().sum(axis=0).replace(0.0,np.nan); scores=x.sum(axis=0)/denom
        if scores.notna().sum()<6: continue
        signals.append((i+1,i+2,_rank(scores,long_high=not bool(reverse)).reindex(opens.columns,fill_value=0.0)))
    return _simulate_signals(signals,opens,funding_frames,side_cost_bps=side_cost_bps)


def realized_semivariance_balance(daily_frames, *, symbols, funding_frames, lookback_days, common_warmup_days, side_cost_bps, reverse=False) -> VariantRun:
    opens, closes = _validate_price_frames(daily_frames, symbols); ret=closes.pct_change(); signals=[]
    for i in range(int(common_warmup_days),len(opens)-2):
        x=ret.iloc[i-int(lookback_days)+1:i+1]
        pos=x.clip(lower=0.0).pow(2).sum(axis=0); neg=x.clip(upper=0.0).pow(2).sum(axis=0); den=(pos+neg).replace(0.0,np.nan)
        scores=(pos-neg)/den
        if scores.notna().sum()<6: continue
        signals.append((i+1,i+2,_rank(scores,long_high=not bool(reverse)).reindex(opens.columns,fill_value=0.0)))
    return _simulate_signals(signals,opens,funding_frames,side_cost_bps=side_cost_bps)


def evaluate_sprint6_family(variants: Mapping[str,VariantRun], controls: Mapping[str,VariantRun], *, ordered_variant_ids: Sequence[str], evaluation_config: Mapping[str,Any], principal_control_for_variant: Mapping[str,str], gate: Mapping[str,Any]) -> dict[str,Any]:
    out=evaluate_sprint2_family(variants,controls,ordered_variant_ids=ordered_variant_ids,evaluation_config=evaluation_config,principal_control_for_variant=principal_control_for_variant,gate=gate)
    out["sprint6_selected_variant"]=out.pop("sprint2_selected_variant",None)
    out["sprint6_selected_control"]=out.pop("sprint2_selected_control",None)
    out["sprint6_selected_advantage_bps"]=out.pop("sprint2_selected_advantage_bps",None)
    out["sprint6_hard_checks"]=out.pop("sprint2_hard_checks",{})
    return out
