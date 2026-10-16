"""PSR15 frozen anchored range-breakout adaptation; offline hypothetical research only."""
from __future__ import annotations

import argparse
from decimal import Decimal, ROUND_DOWN
from collections import Counter
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys

import numpy as np
import pandas as pd

from . import public_protective_batch5 as shared
from .protective_minute import settle_buy

CANDIDATES = ("DualThrust8hPinnedKernelSpot",)
DESIGN_COMMIT = "43a385e9fe3af963a98dfb32f32be34c0de24106"
DESIGN_SHA256 = "370b90fa59393f0c0ce80e36c0061df7be4779e1302306a9b1cfcd734e1c9c34"
mean = shared.mean
block_draws = shared.block_draws
enrich = shared.enrich
joint_histories = shared.joint_histories
summary = shared.summary
event_diagnostics = shared.event_diagnostics
portfolio = shared.portfolio
gate_checks = shared.gate_checks
randomized_flags = shared.randomized_flags


def source_features(candles: np.ndarray, candidate: str, spec: dict, native=None) -> dict:
    if candidate not in CANDIDATES or native is None:
        raise ValueError('registered candidate and selected native kernel required')
    if candles.ndim != 2 or candles.shape[1] != 6 or not len(candles):
        raise ValueError('nonempty candle matrix required')
    if not np.isfinite(candles).all() or (candles[:,1:5] <= 0).any() or (candles[:,5] < 0).any():
        raise ValueError('invalid source candles')
    times=candles[:,0]
    if times[0] % 86400000 or not np.array_equal(times,times[0]+np.arange(len(times))*28800000):
        raise ValueError('known daily00 open and continuous8h grid required')
    p=spec['dual_thrust']
    close,high,low=(candles[:,j] for j in (2,3,4))
    atr=np.full(len(candles),np.nan)
    anchor=np.empty(len(candles))
    upper=np.full(len(candles),np.nan)
    lower=np.full(len(candles),np.nan)
    for i in range(len(candles)):
        anchor[i]=candles[i-i%3,1]
        if i+1 >= p['atr_period']:
            window=np.ascontiguousarray(candles[max(0,i+1-p['native_nonsequential_window']):i+1])
            atr[i]=native.atr_last(window,p['atr_period'])
        start=max(0,i+1-p['up_length'])
        span=max(float(close[start:i+1].max()-low[start:i+1].min()),float(high[start:i+1].max()-close[start:i+1].min()))
        upper[i]=float(anchor[i])+p['up_coeff']*span
        start=max(0,i+1-p['down_length'])
        span=max(float(close[start:i+1].max()-low[start:i+1].min()),float(low[start:i+1].max()-close[start:i+1].min()))
        lower[i]=float(anchor[i])-p['down_coeff']*span
    return dict(long=close>upper,short=close<lower,close=close.copy(),opening=candles[:,1].copy(),
                atr=atr,anchor=anchor,upper=upper,lower=lower)


def floor8(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal('0.00000001'),rounding=ROUND_DOWN))


def source_quantity(cash: float, signal: float, stop: float, side: float, spec: dict) -> tuple[float,float,float]:
    if not np.isfinite([cash,signal,stop,side]).all() or not 0 < stop < signal or cash <= 0 or not 0 <= side < 1:
        raise ValueError('invalid sizing inputs')
    risk=cash*spec['dual_thrust']['risk_fraction']
    quote=min((risk/(signal-stop))*signal,cash)
    source_q=floor8(quote/signal)
    quantity=floor8(min(source_q,cash/(signal*(1+side))))
    return quantity,quote,source_q


def _close(state,data,btc,j,price,side,reason,at_open):
    p=state['position']
    shared.settle_position(state,data,btc,j,price,side,reason,at_open)
    state['events'][-1].update(signal_close=p['signal_close'],entry_atr=p['entry_atr'],
                               source_quote=p['source_quote'],source_quantity=p['source_quantity'])


def simulate(data, btc, candles, features, candidate, spec, cost, gap_model, *, entry_flags=None):
    if candidate not in CANDIDATES or cost not in spec['cost_cases_bps'] or gap_model not in spec['gap_target_models']:
        raise ValueError('unregistered execution model')
    if data.shape != btc.shape or not np.array_equal(data[:,0],btc[:,0]) or not np.array_equal(shared.bars8h(data),candles):
        raise ValueError('unaligned execution model')
    if any(len(features[k]) != len(candles) for k in ('long','short','atr')):
        raise ValueError('feature length mismatch')
    flags=features['long'] if entry_flags is None else entry_flags
    if len(flags) != len(candles):
        raise ValueError('control flag length mismatch')
    side=cost/20000
    initial=float(spec['episode_initial_cash_per_symbol'])
    state=dict(cash=initial,btc_cash_lower=initial,btc_cash_upper=initial,position=None,
               events=[],counts=Counter(),nav=[initial],btc_nav_lower=[initial],btc_nav_upper=[initial])
    for b in range(spec['warmup_bars'],len(candles)):
        i,begin,end=b-1,b*480,(b+1)*480
        held=state['position'] is not None
        if flags[i]:
            state['counts']['raw_entry_flags']+=1
            if held:
                state['counts']['held_entry_ignored']+=1
        if held and features['short'][i]:
            _close(state,data,btc,begin,float(data[begin,1]),side,'source_short_to_cash',True)
        if not held and flags[i]:
            signal,atr=float(candles[i,2]),float(features['atr'][i])
            stop=signal-spec['dual_thrust']['stop_loss_atr_rate']*atr
            if not np.isfinite([signal,atr,stop]).all() or not 0 < stop < signal or atr <= 0:
                state['counts']['invalid_entry']+=1
            else:
                qty,quote,source_q=source_quantity(state['cash'],signal,stop,side,spec)
                buy=settle_buy(state['cash'],qty,float(data[begin,1]),side_bps=side*10000)
                if not buy.accepted:
                    state['counts']['cash_rejected' if buy.reason=='insufficient_cash' else 'zero_quantity']+=1
                else:
                    fraction=qty*buy.reference_price/state['cash']
                    qlo=state['btc_cash_lower']*fraction/float(btc[begin,1])
                    qhi=state['btc_cash_upper']*fraction/float(btc[begin,1])
                    state['btc_cash_lower']-=qlo*float(btc[begin,1])*(1+side)
                    state['btc_cash_upper']-=qhi*float(btc[begin,1])*(1+side)
                    if min(state['btc_cash_lower'],state['btc_cash_upper']) < -1e-8:
                        raise ValueError('unfunded benchmark')
                    state['btc_cash_lower']=max(0,state['btc_cash_lower'])
                    state['btc_cash_upper']=max(0,state['btc_cash_upper'])
                    state['cash'],state['position']=buy.remaining_cash,dict(entry_index=begin,entry_price=buy.reference_price,
                        quantity=qty,stop=stop,target=None,initial_stop=stop,initial_target=None,
                        signal_close=signal,entry_atr=atr,source_quote=quote,source_quantity=source_q,
                        btc_entry=float(btc[begin,1]),btc_quantity_lower=qlo,btc_quantity_upper=qhi,
                        signal_time=shared.stamp(int(data[begin,0])),decided_at=int(data[begin,0]))
                    state['counts']['accepted_entries']+=1
        p=state['position']
        if p is not None:
            hits=np.flatnonzero(data[begin:end,3] <= p['stop'])
            if len(hits):
                j=begin+int(hits[0])
                gap=bool(data[j,1] <= p['stop'])
                price=float(data[j,1]) if gap else p['stop']
                _close(state,data,btc,j,price,side,'stop_gap' if gap else 'stop_touch',gap)
        values=shared.mark(state,float(data[end-1,4]),float(btc[end-1,4]),side)
        if not np.isfinite(values).all() or min(values)<=0:
            raise ValueError('invalid portfolio wealth')
        for key,value in zip(('nav','btc_nav_lower','btc_nav_upper'),values):
            state[key].append(value)
    if flags[-1]:
        state['counts']['raw_entry_flags']+=1
        state['counts']['held_entry_ignored' if state['position'] is not None else 'unexecuted_final_entry']+=1
    p=state['position']
    if p is not None:
        event=shared.event_record(p,data,btc,len(data)-1,float(data[-1,4]),side,'fixed_cutoff_mark',False,censored=True)
        event.update(signal_close=p['signal_close'],entry_atr=p['entry_atr'],source_quote=p['source_quote'],source_quantity=p['source_quantity'])
        state['events'].append(event)
        state['pending_source_exit']=bool(features['short'][-1])
    account=state['counts']
    if account['raw_entry_flags'] != sum(account[k] for k in ('held_entry_ignored','invalid_entry','cash_rejected','zero_quantity','accepted_entries','unexecuted_final_entry')) or account['accepted_entries'] != len(state['events']):
        raise ValueError('signal/admission accounting failed')
    state['counts']=dict(account)
    return [state]


def event_diagnostics(events, spec, draws):
    result = shared.event_diagnostics(events,spec,draws)
    result['bootstrap'].update(alpha_policy='Fixed0.025 conservative carryover from previous two-cell comparator; only1new registered cell; no global search correction',new_registered_cells=1)
    return result


def require_pre_outcome_review(root: Path, spec: dict, source: Path) -> dict:
    contract=spec['required_pre_outcome_review']
    path=root/contract['path']
    if not path.is_file():
        raise ValueError('INDEPENDENT_PRE_OUTCOME_REVIEW_REQUIRED before market data load')
    raw=path.read_bytes()
    review=json.loads(raw)
    if (review.get('status')!=contract['required_status'] or review.get('blocking_findings')!=[]
            or review.get('market_outcomes_inspected') is not False
            or review.get('evaluator_exact_sha256')!=shared.sha(source)
            or review.get('canonical_config_sha256')!=shared.digest(spec)):
        raise ValueError('INDEPENDENT_PRE_OUTCOME_REVIEW_BINDING_FAILED')
    try:
        committed=subprocess.check_output(['git','show',f"HEAD:{contract['path']}"],cwd=root,stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError as error:
        raise ValueError('commit independent review before outcomes') from error
    if committed!=raw:
        raise ValueError('changed uncommitted independent review')
    return review


def _evaluate_candidate(candidate: str, panel: dict, frames: dict, features: dict, spec: dict, output_progress=print) -> dict:
    cases = {}
    draws = block_draws(spec, spec["seed"] + CANDIDATES.index(candidate))
    for cost in spec["cost_cases_bps"]:
        for gap in spec["gap_target_models"]:
            histories = {}
            for symbol in spec["symbols"]:
                states = simulate(panel[symbol], panel[spec["benchmark"]], frames[symbol], features[symbol], candidate, spec, cost, gap)
                enrich(states, symbol, frames[spec["benchmark"]])
                histories[symbol] = states
            joints = []
            for indexes, states in enumerate(joint_histories(histories, spec)):
                events = [e for state in states for e in state["events"]]
                joints.append({"joint_id": indexes, "summary": summary(events), "diagnostics": event_diagnostics(events, spec, draws), "portfolio": portfolio(states)})
            cases[f"{cost}:{gap}"] = {"symbols": histories, "joint_histories": joints}
            output_progress(json.dumps({"candidate": candidate, "cost": cost, "gap_model": gap, "joint_histories": len(joints),
                                        "admitted": joints[0]["summary"]["admitted"], "completed": joints[0]["summary"]["completed"]}), flush=True)
    originals = [joint for key, case in cases.items() if key.startswith("40:") for joint in case["joint_histories"]]
    observed_minimum = min((j["summary"]["mean_net_bps"] for j in originals if j["summary"]["mean_net_bps"] is not None), default=None)
    stress = [j["summary"]["mean_net_bps"] for key, case in cases.items() if key.startswith("80:") for j in case["joint_histories"]]
    stress_minimum = min(stress) if stress and all(value is not None for value in stress) else None
    rng = np.random.default_rng(spec["seed"] + 100 + CANDIDATES.index(candidate))
    control_means = []
    for repetition in range(spec["placebo_replicates"]):
        flags = {s: randomized_flags(features[s]["long"], frames[s], spec, rng) for s in spec["symbols"]}
        maxima = []
        for gap in spec["gap_target_models"]:
            histories = {}
            for symbol in spec["symbols"]:
                histories[symbol] = simulate(panel[symbol], panel[spec["benchmark"]], frames[symbol], features[symbol], candidate, spec, 40, gap, entry_flags=flags[symbol])
            for states in joint_histories(histories, spec):
                value = mean([e["net_bps"] for s in states for e in s["events"]])
                if value is not None:
                    maxima.append(value)
        control_means.append(max(maxima) if maxima else None)
        if (repetition + 1) % 50 == 0:
            output_progress(json.dumps({"candidate": candidate, "randomized_entry_controls_done": repetition + 1}), flush=True)
    tail = sum(x is None or observed_minimum is None or x >= observed_minimum for x in control_means) / len(control_means)
    lagged = {}
    for gap in spec["gap_target_models"]:
        histories = {}
        for symbol in spec["symbols"]:
            flags = np.zeros(len(frames[symbol]), dtype=bool)
            eligible = features[symbol]["long"].copy()
            eligible[:spec["warmup_bars"] - 1] = False
            flags[spec["lag_control_bars"]:] = eligible[:-spec["lag_control_bars"]]
            histories[symbol] = simulate(panel[symbol], panel[spec["benchmark"]], frames[symbol], features[symbol], candidate, spec, 40, gap, entry_flags=flags)
            enrich(histories[symbol], symbol, frames[spec["benchmark"]])
        lagged[gap] = [summary([e for s in states for e in s["events"]]) for states in joint_histories(histories, spec)]
    checks = [gate_checks(j, stress_minimum, tail, spec) for j in originals]
    failed = sorted({key for record in checks for key, passed in record.items() if not passed})
    return {"candidate": candidate, "decision": "REJECTED_AS_ADAPTED" if failed else "SCREEN_SURVIVOR_FOR_FUTURE_REGISTRATION",
            "failed_gates": failed, "gate_checks_all_baseline_joint_histories": checks, "cost_and_gap_cases": cases,
            "randomized_entry_control": {"replicates": len(control_means), "maximum_cohort_mean_per_rep": control_means,
                                         "original_minimum_cohort_mean": observed_minimum, "tail_fraction_at_least_observed": tail,
                                         "endogenous_durations_reused": False, "descriptive_only": True},
            "seven_bar_lag_control": lagged, "viable": False, "future_confirmation_started": False}


def evaluate_candidate(candidate: str, panel: dict, frames: dict, features: dict, spec: dict, output_progress=print) -> dict:
    try:
        return _evaluate_candidate(candidate, panel, frames, features, spec, output_progress)
    except ValueError as error:
        if "HISTORY_LIMIT_EXCEEDED" not in str(error):
            raise
        # Never prune ambiguous histories to manufacture a tractable survivor.
        return {"candidate": candidate, "decision": "REJECTED_AS_ADAPTED", "failed_gates": ["no_history_overflow"],
                "evaluation_complete": False, "error": str(error), "viable": False,
                "future_confirmation_started": False,
                "note": "Registered history limit reached in a baseline or control; exhaustive evaluation unavailable. No history pruning or rule change."}


def checked_spec(root, path):
    spec = json.loads(path.read_text())
    if shared.digest(spec) != DESIGN_SHA256:
        raise ValueError('changed frozen design')
    committed = json.loads(subprocess.check_output(['git','show',f'{DESIGN_COMMIT}:{path.relative_to(root).as_posix()}'],cwd=root))
    if spec != committed:
        raise ValueError('design not registered')
    for name,expected in spec['dependency_source_sha256'].items():
        if hashlib.sha256((root/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest() != expected:
            raise ValueError('changed frozen dependency')
    bindings = dict(spec['source_mechanics_audit_sha256'])
    bindings.update({spec['source_manifest']:spec['source_manifest_sha256'], spec['quality_csv']:spec['quality_csv_sha256']})
    for name,expected in bindings.items():
        if shared.sha(root/name) != expected:
            raise ValueError('changed frozen dependency/provenance')
    return spec


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path.cwd())
    parser.add_argument('--config',type=Path,default=Path('config/public_dual_thrust_batch9_v1.json'))
    parser.add_argument('--raw',type=Path,required=True)
    parser.add_argument('--cache',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--native-runtime',type=Path,default=Path('../magen_native_runtime'))
    parser.add_argument('--native-wheel',type=Path,default=Path('../magen_native_wheels/jesse_rust-1.3.0-cp313-cp313-win_amd64.whl'))
    args = parser.parse_args()
    root = args.root.resolve()
    if args.output.exists():
        raise ValueError('retain prior attempts; choose new output')
    spec = checked_spec(root,(root/args.config).resolve())
    actual = dict(python=platform.python_version(),numpy=np.__version__,pandas=pd.__version__,platform=sys.platform)
    if any(actual[k] != spec['runtime'][k] for k in actual):
        raise ValueError('runtime differs from freeze')
    path = Path(__file__).resolve()
    source = subprocess.check_output(['git','show',f'HEAD:{path.relative_to(root).as_posix()}'],cwd=root)
    if source.replace(b'\r\n',b'\n') != path.read_bytes().replace(b'\r\n',b'\n'):
        raise ValueError('commit evaluator before outcomes')
    review = require_pre_outcome_review(root,spec,path)
    native=shared.native_kernel(args.native_runtime,args.native_wheel,spec)
    panel,evidence = shared.retained_panel(root,args.raw,args.cache,spec)
    frames = {s:shared.bars8h(data) for s,data in panel.items()}
    results = []
    for candidate in CANDIDATES:
        features = {s:source_features(frames[s],candidate,spec,native) for s in spec['symbols']}
        results.append(evaluate_candidate(candidate,panel,frames,features,spec))
    report = dict(study_id=spec['study_id'],design_commit=DESIGN_COMMIT,design_sha256=DESIGN_SHA256,
                  evaluator_git_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),
                  evaluator_source_sha256=shared.sha(path),pre_outcome_review_source_sha256=review['evaluator_exact_sha256'],runtime=actual,source=evidence,results=results,
                  claim=spec['claim'],new_tested_trading_cells=1,minimum_cumulative_trading_cells=22,
                  minimum_cumulative_signal_model_cells=23,viable_candidates=[],orders=False,
                  frozen_lanes_modified=False,future_untouched_confirmation_required=True)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(output=str(args.output),sha256=shared.sha(args.output),decisions=[(r['candidate'],r['decision'],r['failed_gates']) for r in results])))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
