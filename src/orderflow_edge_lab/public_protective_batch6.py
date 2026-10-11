"""PSR12 frozen source adaptations; offline hypothetical research only."""
from __future__ import annotations

import argparse
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
from .protective_minute import fixed_risk_quantity, settle_buy

CANDIDATES = ("PSARReference8hSpot", "CMF21Spot8hMinuteCloseROI")
DESIGN_COMMIT = "eaaef0c1845cc56cc5ba4d20413153e85b65b377"
DESIGN_SHA256 = "a654938094a1133981e397ada4c92c438c83b336174ad0a1b5bc96b6d3aed4c5"
mean = shared.mean
block_draws = shared.block_draws
enrich = shared.enrich
joint_histories = shared.joint_histories
summary = shared.summary
event_diagnostics = shared.event_diagnostics
portfolio = shared.portfolio
gate_checks = shared.gate_checks
randomized_flags = shared.randomized_flags


def sar_reference(candles: np.ndarray, start=.02, increment=.02, maximum=.2) -> np.ndarray:
    """Independent scalar math of official documented recurrence, fixed origin."""
    result = np.full(len(candles), np.nan)
    if len(candles) < 2:
        return result
    bull = bool(candles[1, 2] > candles[0, 2])
    extreme = float(candles[1, 3] if bull else candles[1, 4])
    value = float(candles[0, 4] if bull else candles[0, 3])
    acceleration = start
    for i in range(1, len(candles)):
        first = i == 1
        value = value + acceleration * (extreme - value)
        high, low = float(candles[i, 3]), float(candles[i, 4])
        if bull and value > low:
            bull, first = False, True
            value, extreme, acceleration = max(extreme, high), low, start
        elif not bull and value < high:
            bull, first = True, True
            value, extreme, acceleration = min(extreme, low), high, start
        if not first:
            if bull and high > extreme:
                extreme, acceleration = high, min(acceleration + increment, maximum)
            elif not bull and low < extreme:
                extreme, acceleration = low, min(acceleration + increment, maximum)
        opposite = candles[max(0, i-2):i, 4 if bull else 3]
        value = min(value, float(opposite.min())) if bull else max(value, float(opposite.max()))
        result[i] = value
    return result


def source_features(candles: np.ndarray, candidate: str, spec: dict) -> dict:
    close, high, low, volume = (candles[:, j] for j in (2, 3, 4, 5))
    if candidate == CANDIDATES[0]:
        p = spec['psar']
        sar = sar_reference(candles, p['start'], p['increment'], p['maximum'])
        prior_close, prior_sar = np.r_[np.nan, close[:-1]], np.r_[np.nan, sar[:-1]]
        long = (close > sar) & (prior_close <= prior_sar)
        short = (close < sar) & (prior_close >= prior_sar)
        tr = np.maximum(high-low, np.maximum(abs(high-np.r_[close[0], close[:-1]]), abs(low-np.r_[close[0], close[:-1]])))
        atr = np.full(len(close), np.nan)
        period = p['atr_period']
        if len(close) >= period:
            atr[period-1] = np.mean(tr[:period])
            for i in range(period, len(close)):
                atr[i] = atr[i-1] + (tr[i]-atr[i-1])/period
        return dict(long=long, short=short, exit=short, atr=atr, sar=sar,
                    stop_atr=p['stop_atr'], target_atr=p['target_atr'], risk_fraction=None)
    if candidate != CANDIDATES[1]:
        raise ValueError('unregistered candidate')
    period = spec['cmf']['period']
    with np.errstate(divide='ignore', invalid='ignore'):
        flow = ((close-low)-(high-close))/(high-low)*volume
        cmf = (pd.Series(flow).rolling(period, min_periods=period).sum()
               / pd.Series(volume).rolling(period, min_periods=period).sum()).to_numpy()
    return dict(long=cmf < 0, short=cmf > 0, exit=cmf > 0, cmf=cmf)


def roi_observed(price: float, entry: float, spec: dict) -> bool:
    p = spec['cmf']
    fee = p['roi_fee_each_side']
    profit = (price * (1-fee) / (entry * (1+fee))) - 1
    return round(profit, p['roi_profit_round_decimals']) > p['minimal_roi']


def simulate_cmf(data, btc, candles, features, spec, cost, *, entry_flags=None):
    if cost not in spec['cost_cases_bps'] or data.shape != btc.shape or not np.array_equal(data[:,0],btc[:,0]) or not np.array_equal(shared.bars8h(data),candles):
        raise ValueError('unregistered/unaligned execution model')
    if any(len(features[k]) != len(candles) for k in ('long','exit')):
        raise ValueError('feature length mismatch')
    flags = features['long'] if entry_flags is None else entry_flags
    if len(flags) != len(candles):
        raise ValueError('control flag length mismatch')
    side = cost/20000
    initial = float(spec['episode_initial_cash_per_symbol'])
    state = dict(cash=initial, btc_cash_lower=initial, btc_cash_upper=initial, position=None,
                 events=[], counts=Counter(), nav=[initial], btc_nav_lower=[initial], btc_nav_upper=[initial])
    pending_roi = False
    pending_roi_decision_time = None
    for b in range(spec['warmup_bars'], len(candles)):
        i, begin, end = b-1, b*480, (b+1)*480
        p = state['position']
        had_position = p is not None
        if flags[i]:
            state['counts']['raw_entry_flags'] += 1
            if had_position:
                state['counts']['held_entry_ignored'] += 1
        if p is not None and (features['exit'][i] or pending_roi):
            reason = 'source_signal_exit' if features['exit'][i] else 'observed_minute_roi_next_open'
            shared.settle_position(state, data, btc, begin, float(data[begin,1]), side, reason, True)
            p, pending_roi = None, False
        if not had_position and flags[i]:
            signal_price = float(candles[i,2])
            qty = fixed_risk_quantity(state['cash'], signal_price, signal_price*.95, risk_fraction=1, reserve_side_bps=side*10000)
            buy = settle_buy(state['cash'], qty, float(data[begin,1]), side_bps=side*10000)
            if not buy.accepted:
                state['counts']['cash_rejected' if buy.reason == 'insufficient_cash' else 'zero_quantity'] += 1
            else:
                fraction = qty*buy.reference_price/state['cash']
                qlo = state['btc_cash_lower']*fraction/float(btc[begin,1])
                qhi = state['btc_cash_upper']*fraction/float(btc[begin,1])
                state['btc_cash_lower'] -= qlo*float(btc[begin,1])*(1+side)
                state['btc_cash_upper'] -= qhi*float(btc[begin,1])*(1+side)
                if min(state['btc_cash_lower'],state['btc_cash_upper']) < -1e-8:
                    raise ValueError('unfunded benchmark')
                state['btc_cash_lower'] = max(0,state['btc_cash_lower'])
                state['btc_cash_upper'] = max(0,state['btc_cash_upper'])
                stop = buy.reference_price*(1-spec['cmf']['stop_fraction'])
                p = dict(entry_index=begin, entry_price=buy.reference_price, quantity=qty, stop=stop, target=None,
                         initial_stop=stop, initial_target=None, btc_entry=float(btc[begin,1]),
                         btc_quantity_lower=qlo, btc_quantity_upper=qhi, signal_time=shared.stamp(int(data[begin,0])), decided_at=int(data[begin,0]))
                state['cash'], state['position'] = buy.remaining_cash, p
                state['counts']['accepted_entries'] += 1
        if p is not None:
            window = data[begin:end]
            touches = np.flatnonzero(window[:,3] <= p['stop'])
            stop_index = int(touches[0]) if len(touches) else len(window)
            # Candidate filter avoids expensive Python rounding on obviously losing closes.
            profitable = np.flatnonzero(window[:,4] > p['entry_price'])
            roi_index = next((int(k) for k in profitable if roi_observed(float(window[k,4]),p['entry_price'],spec)), len(window))
            if stop_index <= roi_index and stop_index < len(window):
                j = begin+stop_index
                gap = float(data[j,1]) <= p['stop']
                price = float(data[j,1]) if gap else p['stop']
                shared.settle_position(state,data,btc,j,price,side,'stop_gap' if gap else 'stop_touch',gap)
            elif roi_index < len(window):
                j = begin+roi_index+1
                if j < end:
                    shared.settle_position(state,data,btc,j,float(data[j,1]),side,'observed_minute_roi_next_open',True)
                else:
                    pending_roi = True
                    pending_roi_decision_time = shared.stamp(int(data[j-1,0])+60)
        values = shared.mark(state,float(data[end-1,4]),float(btc[end-1,4]),side)
        if not np.isfinite(values).all() or min(values) <= 0:
            raise ValueError('invalid portfolio wealth')
        for key,value in zip(('nav','btc_nav_lower','btc_nav_upper'),values):
            state[key].append(value)
    if flags[-1]:
        state['counts']['raw_entry_flags'] += 1
        state['counts']['held_entry_ignored' if state['position'] is not None else 'unexecuted_final_entry'] += 1
    if state['position'] is not None:
        state['events'].append(shared.event_record(state['position'],data,btc,len(data)-1,float(data[-1,4]),side,'fixed_cutoff_mark',False,censored=True))
        state['pending_source_exit'] = bool(features['exit'][-1])
        state['pending_observed_roi_exit'] = pending_roi
        state['pending_roi_decision_time'] = pending_roi_decision_time if pending_roi else None
    account = state['counts']
    if account['raw_entry_flags'] != sum(account[k] for k in ('held_entry_ignored','cash_rejected','zero_quantity','accepted_entries','unexecuted_final_entry')) or account['accepted_entries'] != len(state['events']):
        raise ValueError('signal/admission accounting failed')
    state['counts'] = dict(account)
    return [state]


def simulate(data, btc, candles, features, candidate, spec, cost, gap_model, *, entry_flags=None):
    if gap_model not in spec['gap_target_models']:
        raise ValueError('unregistered gap model')
    if candidate == CANDIDATES[0]:
        # Shared source profile reanchors on original qualifying flags, irrespective of controls.
        return shared.simulate(data, btc, candles, features, shared.CANDIDATES[1], spec, cost, gap_model, entry_flags=entry_flags)
    if candidate == CANDIDATES[1]:
        return simulate_cmf(data, btc, candles, features, spec, cost, entry_flags=entry_flags)
    raise ValueError('unregistered candidate')


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
    parser.add_argument('--config',type=Path,default=Path('config/public_protective_batch6_v1.json'))
    parser.add_argument('--raw',type=Path,required=True)
    parser.add_argument('--cache',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
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
    panel,evidence = shared.retained_panel(root,args.raw,args.cache,spec)
    frames = {s:shared.bars8h(data) for s,data in panel.items()}
    results = []
    for candidate in CANDIDATES:
        features = {s:source_features(frames[s],candidate,spec) for s in spec['symbols']}
        results.append(evaluate_candidate(candidate,panel,frames,features,spec))
    report = dict(study_id=spec['study_id'],design_commit=DESIGN_COMMIT,design_sha256=DESIGN_SHA256,
                  evaluator_git_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),
                  evaluator_source_sha256=shared.sha(path),runtime=actual,source=evidence,results=results,
                  claim=spec['claim'],new_tested_trading_cells=2,minimum_cumulative_trading_cells=19,
                  minimum_cumulative_signal_model_cells=20,viable_candidates=[],orders=False,
                  frozen_lanes_modified=False,future_untouched_confirmation_required=True)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(output=str(args.output),sha256=shared.sha(args.output),decisions=[(r['candidate'],r['decision'],r['failed_gates']) for r in results])))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
