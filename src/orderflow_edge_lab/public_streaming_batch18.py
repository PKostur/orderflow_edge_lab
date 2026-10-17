"""PSR24 registered streaming-reversal mathematical research reference.

Own fixed-unit Spot cash adaptation; no broker or exchange order routes.
Selected synthetic source parity only; no default publisher bot parity.
"""
from __future__ import annotations
import argparse
import hashlib
import platform
import subprocess
import sys
import pandas as pd
from pathlib import Path
from collections import Counter
import json
import math
import numpy as np
from orderflow_edge_lab import public_protective_batch5 as shared

CANDIDATES = ('Quickstart06TwoDown8hOneUnitLongCash', 'UpDown40Return8hTenUnitLongCash')
DESIGN_COMMIT = '10340a52195b2f6b46169d5b668b5c2345daf572'
DESIGN_SHA256 = '28deca87c0c3fc03c1c3153f82b12b94dda85891a280962694aea33c1af74936'
mean, block_draws = shared.mean, shared.block_draws
enrich, joint_histories, summary = shared.enrich, shared.joint_histories, shared.summary
portfolio, gate_checks, randomized_flags = shared.portfolio, shared.gate_checks, shared.randomized_flags


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



def debit(cash, quantity, price, side):
    notional = quantity * price
    cash = cash - notional
    return cash - notional * side


def credit(cash, quantity, price, side):
    notional = quantity * price
    cash = cash + notional
    return cash - notional * side


def source_features(candles, candidate, spec):
    if candidate not in CANDIDATES or spec['warmup_bars'] != 240:
        raise ValueError('unsupported fixed draft contract')
    candles = np.asarray(candles, dtype=float)
    if candles.ndim != 2 or candles.shape[1] != 6 or not len(candles):
        raise ValueError('six-column 8h candles required')
    close = candles[:, 2]
    if not np.isfinite(candles).all() or (candles[:, 1:5] <= 0).any() or (candles[:, 5] < 0).any():
        raise ValueError('finite positive prices/nonnegative volume required')
    if (candles[:, 3] < np.maximum(candles[:, 1], close)).any() or (candles[:, 4] > np.minimum(candles[:, 1], close)).any():
        raise ValueError('invalid OHLC')
    long = np.zeros(len(close), dtype=bool)
    leave = long.copy()
    value = np.full(len(close), np.nan)
    if candidate == CANDIDATES[0]:
        long[2:] = (close[2:] < close[1:-1]) & (close[1:-1] < close[:-2])
    else:
        value[40:] = (close[40:] - close[:-40]) / close[:-40]
        long = value < -.01
        leave = value >= .01
    return {'long': long, 'exit_long': leave, 'source_value': value,
            'close': close.copy(), 'opening': candles[:, 1].copy()}


def mark(state, source_price, btc_price, side):
    p = state['position']
    if p is None:
        return state['cash'], state['btc_cash_lower'], state['btc_cash_upper']
    return (credit(state['cash'], p['quantity'], source_price, side),
            credit(state['btc_cash_lower'], p['btc_quantity_lower'], btc_price, side),
            credit(state['btc_cash_upper'], p['btc_quantity_upper'], btc_price, side))


def _position_metadata(p):
    return {k: p[k] for k in ('source_signal_close', 'source_reference_known_at',
                             'source_created_bar', 'source_entry_bar',
                             'source_cash_before_entry', 'source_notional_fraction',
                             'btc_cash_before_entry', 'btc_entry_cost', 'source_entry_cost')}


def _settle(state, data, btc, j, price, side, reason):
    p = state['position']
    event = shared.event_record(p, data, btc, j, price, side, reason, True)
    event.update(_position_metadata(p))
    state['cash'] = credit(state['cash'], p['quantity'], price, side)
    bp = float(btc[j, 1])
    for branch in ('lower', 'upper'):
        state['btc_cash_' + branch] = credit(state['btc_cash_' + branch], p['btc_quantity_' + branch], bp, side)
    event.update(source_cash_after_exit=state['cash'], btc_cash_after_exit=state['btc_cash_lower'],
                 btc_exit_cost=p['btc_quantity_lower'] * bp * side,
                 source_exit_cost=p['quantity'] * price * side)
    event['net_cash_profit_or_cutoff_mark'] = state['cash'] - p['source_cash_before_entry']
    state['events'].append(event)
    state['position'] = None


def simulate(data, btc, candles, features, candidate, spec, cost, gap_model, *, entry_flags=None):
    """Own reference execution; features/data may be synthetic arrays only in draft.

    At OPEN b evaluate requests created at CLOSE b-1. Held state at that close
    fixes intent, so an exit never becomes a same-OPEN entry. After final close,
    a newly queued order has no following OPEN and is retained administratively
    unfilled; inventory is separately CENSORED_MTM with liquidation burden.
    """
    if candidate not in CANDIDATES or cost not in (20, 40, 60, 80) or gap_model not in spec['gap_target_models']:
        raise ValueError('unsupported reference case')
    if spec['warmup_bars'] != 240 or spec['episode_initial_cash_per_symbol'] != 10000:
        raise ValueError('fixed origin/cash required')
    if spec['max_symbol_histories'] != 64 or spec['max_joint_histories'] != 4096:
        raise ValueError('history caps must not change')
    if data.shape != btc.shape or not np.array_equal(data[:, 0], btc[:, 0]) or not np.array_equal(shared.bars8h(data), candles):
        raise ValueError('unaligned execution grid')
    if not np.isfinite(data).all() or not np.isfinite(btc).all() or (data[:, 1:5] <= 0).any() or (btc[:, 1:5] <= 0).any():
        raise ValueError('invalid execution prices')
    n = len(candles)
    if n < 240 or any(len(features[k]) != n for k in ('long', 'exit_long', 'close', 'opening')):
        raise ValueError('insufficient/unaligned feature history')
    if not np.array_equal(features['close'], candles[:, 2]) or not np.array_equal(features['opening'], candles[:, 1]):
        raise ValueError('feature price reference mismatch')
    flags = np.asarray(features['long'] if entry_flags is None else entry_flags)
    if flags.shape != (n,) or flags.dtype.kind != 'b':
        raise ValueError('full boolean qualifier replacement required')
    side, quantity = cost / 20000, (1. if candidate == CANDIDATES[0] else 10.)
    initial = float(spec['episode_initial_cash_per_symbol'])
    state = dict(cash=initial, btc_cash_lower=initial, btc_cash_upper=initial, position=None,
                 events=[], counts=Counter(), orders=[], trace=[], nav=[initial],
                 btc_nav_lower=[initial], btc_nav_upper=[initial], pending_order=None)

    def request(i):
        p = state['position']
        if flags[i]:
            state['counts']['raw_entry_flags'] += 1
            if p is not None:
                state['counts']['held_entry_ignored'] += 1
        leave = (p is not None and (i >= p['source_entry_bar'] + 5 if candidate == CANDIDATES[0] else features['exit_long'][i]))
        if p is None and candidate == CANDIDATES[1] and features['exit_long'][i]:
            state['counts']['upstream_flat_short_refused'] += 1
        if p is None and flags[i]:
            intent = 'ENTRY'
        elif leave:
            intent = 'EXIT'
        else:
            return None
        state['counts']['created_' + intent.lower() + '_orders'] += 1
        order = dict(intent=intent, created_bar=i, created_price=float(candles[i, 2]),
                     due_bar=i + 1, quantity=quantity if intent == 'ENTRY' else p['quantity'],
                     decision_time=shared.stamp(int(candles[i, 0] // 1000) + 28800), status='CREATED')
        state['orders'].append(order)
        return order

    for b in range(240, n):
        i, begin, end = b - 1, b * 480, (b + 1) * 480
        order = request(i)
        state['pending_order'] = order
        if order is not None:
            price, bp = float(data[begin, 1]), float(btc[begin, 1])
            if order['intent'] == 'EXIT':
                _settle(state, data, btc, begin, price, side, 'source_Quick_Eplus6' if candidate == CANDIDATES[0] else 'source_UpDown_return_exit')
                state['counts']['filled_exits'] += 1
                order.update(status='FILLED_EXIT', fill_bar=b, fill_price=price)
            else:
                if debit(state['cash'], quantity, order['created_price'], side) < 0:
                    state['counts']['submission_margin'] += 1
                    order['status'] = 'SUBMISSION_MARGIN'
                elif debit(state['cash'], quantity, price, side) < 0:
                    state['counts']['execution_margin'] += 1
                    order['status'] = 'EXECUTION_MARGIN'
                else:
                    cash_before, btc_before = state['cash'], state['btc_cash_lower']
                    fraction = quantity * price / cash_before
                    bq = btc_before * fraction / bp
                    bcash = debit(btc_before, bq, bp, side)
                    if not math.isfinite(bcash) or bcash < 0:
                        raise ValueError('funded BTC reference margin; do not resize/clamp/prune')
                    state['cash'] = debit(cash_before, quantity, price, side)
                    state['btc_cash_lower'] = state['btc_cash_upper'] = bcash
                    state['position'] = dict(entry_index=begin, entry_price=price, quantity=quantity,
                        stop=None, target=None, initial_stop=None, initial_target=None,
                        source_signal_close=order['created_price'], source_reference_known_at=order['decision_time'],
                        source_created_bar=i, source_entry_bar=b, source_cash_before_entry=cash_before,
                        source_notional_fraction=fraction, btc_cash_before_entry=btc_before,
                        btc_entry_cost=bq * bp * side, source_entry_cost=quantity * price * side,
                        btc_entry=bp, btc_quantity_lower=bq, btc_quantity_upper=bq,
                        signal_time=order['decision_time'], decided_at=int(data[begin, 0]))
                    state['counts']['accepted_entries'] += 1
                    order.update(status='FILLED_ENTRY', fill_bar=b, fill_price=price,
                                 cash_after=state['cash'], btc_cash_after=bcash, btc_quantity=bq)
            state['pending_order'] = None
        values = mark(state, float(data[end - 1, 4]), float(btc[end - 1, 4]), side)
        if not np.isfinite(values).all() or min(values) <= 0:
            raise ValueError('invalid reference wealth')
        for key, value in zip(('nav', 'btc_nav_lower', 'btc_nav_upper'), values):
            state[key].append(value)
        state['trace'].append(dict(bar=b, cash=state['cash'], btc_cash=state['btc_cash_lower'],
                                  quantity=state['position']['quantity'] if state['position'] else 0.,
                                  entry_bar=state['position']['source_entry_bar'] if state['position'] else None))
    final_order = request(n - 1)
    if final_order is not None:
        final_order['status'] = 'FINAL_QUEUED_UNFILLED'
        state['pending_order'] = dict(final_order)
        state['counts']['unexecuted_final_' + final_order['intent'].lower()] += 1
    p = state['position']
    if p is not None:
        event = shared.event_record(p, data, btc, len(data) - 1, float(data[-1, 4]), side,
                                    'fixed_cutoff_mark', False, censored=True)
        event.update(_position_metadata(p))
        event['net_cash_profit_or_cutoff_mark'] = credit(state['cash'], p['quantity'], float(data[-1, 4]), side) - p['source_cash_before_entry']
        state['events'].append(event)
    state['pending_source_exit'] = final_order is not None and final_order['intent'] == 'EXIT'
    counts = state['counts']
    if counts['raw_entry_flags'] != sum(counts[k] for k in ('held_entry_ignored', 'submission_margin', 'execution_margin', 'accepted_entries', 'unexecuted_final_entry')):
        raise ValueError('raw qualifier admission accounting mismatch')
    if counts['accepted_entries'] != len(state['events']):
        raise ValueError('entry event accounting mismatch')
    state['counts'] = dict(counts)
    state['cash_policy'] = 'literal debit/credit; same-fraction BTC owncash/reference not native hedge'
    state['gap_labels_intentionally_identical_no_protection'] = True
    state['exceptional_exchange_orders'] = 'PARTIAL_DELAYED_ASYNCHRONOUS_UNMODELED_FAIL_CLOSED'
    return [state]


def event_diagnostics(events, spec, draws):
    result = shared.event_diagnostics(events, spec, draws)
    result['bootstrap'].update(alpha_policy='Two conditional fixed candidates alpha0.025 each; descriptive, no global search correction', new_registered_cells=2)
    return result

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




def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path.cwd())
    parser.add_argument('--config',type=Path,default=Path('config/public_streaming_batch18_v1.json'))
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
    review = require_pre_outcome_review(root,spec,path)
    panel,evidence = shared.retained_panel(root,args.raw,args.cache,spec)
    frames = {s:shared.bars8h(data) for s,data in panel.items()}
    results = []
    for candidate in CANDIDATES:
        features = {s:source_features(frames[s],candidate,spec) for s in spec['symbols']}
        results.append(evaluate_candidate(candidate,panel,frames,features,spec))
    report = dict(study_id=spec['study_id'],design_commit=DESIGN_COMMIT,design_sha256=DESIGN_SHA256,
                  evaluator_git_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),
                  evaluator_source_sha256=shared.sha(path),pre_outcome_review_source_sha256=review['evaluator_exact_sha256'],runtime=actual,source=evidence,results=results,
                  claim=spec['claim'],new_tested_trading_cells=2,minimum_cumulative_trading_cells=32,
                  minimum_cumulative_signal_model_cells=33,viable_candidates=[],orders=False,
                  frozen_lanes_modified=False,future_untouched_confirmation_required=True)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(output=str(args.output),sha256=shared.sha(args.output),decisions=[(r['candidate'],r['decision'],r['failed_gates']) for r in results])))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
