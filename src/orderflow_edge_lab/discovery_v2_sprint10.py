from __future__ import annotations

from typing import Any, Mapping, Sequence
import numpy as np
import pandas as pd

from orderflow_edge_lab.discovery_v2_sprint1 import VariantRun, _validate_price_frames
from orderflow_edge_lab.discovery_v2_sprint2 import _rank, _simulate_signals, evaluate_sprint2_family


def _run_characteristic(daily_frames, *, symbols, funding_frames, lookback_days, common_warmup_days, side_cost_bps, scorer, long_high, reverse=False):
    opens, closes = _validate_price_frames(daily_frames, symbols)
    ret = closes.pct_change(); n=int(lookback_days); signals=[]
    for i in range(int(common_warmup_days),len(opens)-2):
        window=ret.iloc[i-n+1:i+1]
        scores=scorer(window).replace([np.inf,-np.inf],np.nan)
        if scores.notna().sum()<6: continue
        target=_rank(scores,long_high=(not reverse if long_high else reverse)).reindex(opens.columns,fill_value=0.0)
        signals.append((i+1,i+2,target))
    return _simulate_signals(signals,opens,funding_frames,side_cost_bps=side_cost_bps)


def historical_max_return_momentum(daily_frames, *, symbols, funding_frames, lookback_days, common_warmup_days, side_cost_bps, reverse=False) -> VariantRun:
    return _run_characteristic(daily_frames,symbols=symbols,funding_frames=funding_frames,lookback_days=lookback_days,common_warmup_days=common_warmup_days,side_cost_bps=side_cost_bps,scorer=lambda w:w.max(axis=0),long_high=True,reverse=reverse)


def historical_skewness_premium(daily_frames, *, symbols, funding_frames, lookback_days, common_warmup_days, side_cost_bps, reverse=False) -> VariantRun:
    return _run_characteristic(daily_frames,symbols=symbols,funding_frames=funding_frames,lookback_days=lookback_days,common_warmup_days=common_warmup_days,side_cost_bps=side_cost_bps,scorer=lambda w:-w.skew(axis=0),long_high=True,reverse=reverse)


def historical_kurtosis_premium(daily_frames, *, symbols, funding_frames, lookback_days, common_warmup_days, side_cost_bps, reverse=False) -> VariantRun:
    return _run_characteristic(daily_frames,symbols=symbols,funding_frames=funding_frames,lookback_days=lookback_days,common_warmup_days=common_warmup_days,side_cost_bps=side_cost_bps,scorer=lambda w:w.kurt(axis=0),long_high=True,reverse=reverse)


def evaluate_sprint10_family(variants:Mapping[str,VariantRun],controls:Mapping[str,VariantRun],*,ordered_variant_ids:Sequence[str],evaluation_config:Mapping[str,Any],principal_control_for_variant:Mapping[str,str],gate:Mapping[str,Any])->dict[str,Any]:
    out=evaluate_sprint2_family(variants,controls,ordered_variant_ids=ordered_variant_ids,evaluation_config=evaluation_config,principal_control_for_variant=principal_control_for_variant,gate=gate)
    out["sprint10_selected_variant"]=out.pop("sprint2_selected_variant",None)
    out["sprint10_selected_control"]=out.pop("sprint2_selected_control",None)
    out["sprint10_selected_advantage_bps"]=out.pop("sprint2_selected_advantage_bps",None)
    out["sprint10_hard_checks"]=out.pop("sprint2_hard_checks",{})
    return out
