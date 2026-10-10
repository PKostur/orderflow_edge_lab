"""One specified state-first monthly momentum study on spent Spot data."""
from __future__ import annotations

import argparse
import json
import random
import subprocess
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median

from .public_strategy_development import path_metrics
from .public_strategy_shadow import Bar, iso, read_bars, sha256_file, utc

STEP = timedelta(hours=8)
SYMBOLS = ('ETH_USDT', 'SOL_USDT', 'LINK_USDT')


def month_shift(date: datetime, months: int) -> datetime:
    count = date.year * 12 + date.month - 1 + months
    year, month = divmod(count, 12)
    return date.replace(year=year, month=month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)


def observations(frames: dict[str, list[Bar]]) -> list[dict]:
    grid = [b.timestamp for b in frames['BTC_USDT']]
    if any([b.timestamp for b in frames[s]] != grid for s in SYMBOLS):
        raise ValueError('identical complete grids required')
    if any(b - a != STEP for a, b in zip(grid, grid[1:])):
        raise ValueError('8h continuity required')
    index = {t: i for i, t in enumerate(grid)}
    complete = set()
    for t in grid:
        if t.day == 1 and t.hour == 0:
            # A complete source month needs every held bar; its exit mark is separate.
            end = month_shift(t, 1)
            if end - STEP in index and index[end - STEP] - index[t] + 1 == int((end - t) / STEP):
                complete.add(t)
    rows = []
    for start in sorted(complete):
        previous = month_shift(start, -1)
        formation = month_shift(start, -13)
        end = month_shift(start, 1)
        if previous not in complete or formation not in complete or end not in index:
            continue
        if any(month_shift(start, -m) not in complete for m in range(1, 14)):
            continue
        i, j = index[start], index[end]
        close_i, close_j = index[start - STEP], index[month_shift(start, -12) - STEP]
        btc_return = (frames['BTC_USDT'][j].open / frames['BTC_USDT'][i].open - 1) * 10000
        for s in SYMBOLS:
            bars = frames[s]
            momentum = bars[close_i].close / bars[close_j].close - 1
            gross = (bars[j].open / bars[i].open - 1) * 10000
            rows.append({'symbol': s, 'month': start.strftime('%Y-%m'), 'year': start.year,
                         'signal_observed_at_utc': iso(start), 'entry_time': iso(start), 'exit_time': iso(end),
                         'entry_index': i, 'exit_index': j, 'prior12m_return': momentum,
                         'positive_state': momentum > 0, 'gross_bps': gross, 'btc_gross_bps': btc_return,
                         'excess_bps': gross - btc_return, **path_metrics(bars, i, j, bars[i].open, 40)})
    return rows


def state_effect(rows: list[dict]) -> float | None:
    positive = [r['excess_bps'] for r in rows if r['positive_state']]
    other = [r['excess_bps'] for r in rows if not r['positive_state']]
    return mean(positive) - mean(other) if positive and other else None


def state_summary(rows: list[dict]) -> dict:
    positive = [r for r in rows if r['positive_state']]
    other = [r for r in rows if not r['positive_state']]
    return {'observations': len(rows), 'months': len({r['month'] for r in rows}),
            'positive': len(positive), 'nonpositive': len(other), 'effect_bps': state_effect(rows),
            'positive_mean_gross_bps': mean(r['gross_bps'] for r in positive) if positive else None,
            'nonpositive_mean_gross_bps': mean(r['gross_bps'] for r in other) if other else None,
            'positive_mean_excess_bps': mean(r['excess_bps'] for r in positive) if positive else None,
            'nonpositive_mean_excess_bps': mean(r['excess_bps'] for r in other) if other else None,
            'direction_accuracy': mean(r['positive_state'] == (r['gross_bps'] > 0) for r in rows),
            'always_up_accuracy': mean(r['gross_bps'] > 0 for r in rows)}


def interval(values: list[float]) -> list[float]:
    ordered = sorted(values)
    return [ordered[int(len(ordered) * .01)], ordered[min(len(ordered) - 1, int(len(ordered) * .99))]]


def cluster_analysis(rows: list[dict]) -> dict:
    groups = defaultdict(list)
    for row in rows:
        groups[row['month']].append(row)
    months = sorted(groups)
    rng = random.Random(20261010)
    draws = []
    invalid = 0
    for _ in range(2000):
        sample_months = []
        while len(sample_months) < len(months):
            start = rng.randrange(len(months))
            sample_months.extend(months[(start + j) % len(months)] for j in range(3))
        sample = [r for m in sample_months[:len(months)] for r in groups[m]]
        effect = state_effect(sample)
        if effect is None:
            invalid += 1
        else:
            draws.append(effect)
    leave = [state_effect([r for r in rows if r['month'] != m]) for m in months]
    return {'months': len(months), 'block_length_months': 3, 'seed': 20261010,
            'bootstrap_requested': 2000, 'bootstrap_valid': len(draws), 'invalid_one_state_samples': invalid,
            'descriptive_98pct_effect_interval_bps': interval(draws) if draws else None,
            'leave_one_month_out_effect_range_bps': [min(x for x in leave if x is not None), max(x for x in leave if x is not None)],
            'leave_one_symbol_out_effect_bps': {s: state_effect([r for r in rows if r['symbol'] != s]) for s in SYMBOLS}}


def trade_summary(rows: list[dict], cost: float) -> dict:
    if not rows:
        return {'n': 0}
    net = [r['gross_bps'] - cost for r in rows]
    wins, losses = sum(x for x in net if x > 0), -sum(x for x in net if x < 0)
    return {'n': len(rows), 'months': len({r['month'] for r in rows}),
            'symbols': len({r['symbol'] for r in rows}), 'gross_expectancy_bps': mean(r['gross_bps'] for r in rows),
            'net_gross_minus_cost_bps': mean(net), 'median_net_bps': median(net),
            'matched_btc_net_bps': mean(r['btc_gross_bps'] - cost for r in rows),
            'mean_excess_bps': mean(r['excess_bps'] for r in rows), 'win_rate': mean(x > 0 for x in net),
            'profit_factor': wins / losses if losses else None, 'worst_net_bps': min(net), 'best_net_bps': max(net),
            'mean_mfe_bps': mean(r['mfe_bps'] for r in rows), 'median_mfe_bps': median(r['mfe_bps'] for r in rows),
            'mean_mae_bps': mean(r['mae_bps'] for r in rows), 'median_mae_bps': median(r['mae_bps'] for r in rows)}


def portfolio(rows: list[dict], frames: dict[str, list[Bar]], cost: float) -> dict:
    if not rows:
        return {'return_pct': 0.0, 'max_drawdown_pct': 0.0,
                'per_sleeve_return_pct': {s: 0.0 for s in SYMBOLS}, 'roundtrip_cost_bps': cost,
                'cash_return': 0, 'accounting': 'no selected trades; all cash'}
    starts = {(r['symbol'], r['entry_index']) for r in rows}
    ends = {(r['symbol'], r['exit_index']) for r in rows}
    equity = {s: 1.0 for s in SYMBOLS}
    active = {s: False for s in SYMBOLS}
    first = min(r['entry_index'] for r in rows)
    last = max(r['exit_index'] for r in rows)
    curve = [1.0]
    factor = 1 - cost / 20000
    for i in range(first, last + 1):
        for s in SYMBOLS:
            if (s, i) in ends:
                if not active[s]:
                    raise ValueError('exit without entry')
                equity[s] *= factor
                active[s] = False
            if (s, i) in starts:
                if active[s]:
                    raise ValueError('overlapping month trade')
                equity[s] *= factor
                active[s] = True
        curve.append(mean(equity.values()))
        if i < last:
            for s in SYMBOLS:
                if active[s]:
                    equity[s] *= frames[s][i + 1].open / frames[s][i].open
    if any(active.values()):
        raise ValueError('unclosed portfolio')
    peak = 1.0
    dd = 0.0
    for value in curve:
        peak = max(peak, value)
        dd = min(dd, value / peak - 1)
    return {'return_pct': (curve[-1] - 1) * 100, 'max_drawdown_pct': dd * 100,
            'per_sleeve_return_pct': {s: (v - 1) * 100 for s, v in equity.items()},
            'roundtrip_cost_bps': cost, 'cash_return': 0,
            'accounting': 'equal initial one-third sleeves; monthly close/reopen; multiplicative half-cost each side; held8h open marks'}


def timing_controls(rows: list[dict]) -> dict:
    groups = defaultdict(list)
    for r in rows:
        groups[r['month']].append(r)
    months = sorted(groups)
    selected = [r for r in rows if r['positive_state']]
    observed = mean(r['excess_bps'] for r in selected)
    rng = random.Random(20261010)
    years = defaultdict(list)
    for m in months:
        years[m[:4]].append(m)
    draws = []
    for _ in range(500):
        mapping = {}
        for values in years.values():
            shuffled = values[:]
            rng.shuffle(shuffled)
            mapping.update(zip(values, shuffled))
        chosen = []
        for m in months:
            states = {r['symbol']: r['positive_state'] for r in groups[mapping[m]]}
            chosen.extend(r['excess_bps'] for r in groups[m] if states[r['symbol']])
        draws.append(mean(chosen))
    delayed = []
    for a, b in zip(months, months[1:]):
        states = {r['symbol']: r['positive_state'] for r in groups[a]}
        delayed.extend(r for r in groups[b] if states[r['symbol']])
    return {'within_year_shared_month_permutation': {'replicates': 500, 'seed': 20261010,
             'mean_excess_bps': mean(draws), 'descriptive_98pct_range_bps': interval(draws),
             'fraction_at_least_observed': mean(x >= observed for x in draws),
             'limitations': 'preserves yearly symbol state counts and shared month mapping, not runs or full serial dependence; noncausal placebo, not trading model or p-value'},
            'one_month_delayed_state_reference40': trade_summary(delayed, 40)}


def analyze(rows: list[dict], frames: dict[str, list[Bar]], spec: dict) -> dict:
    positive = [r for r in rows if r['positive_state']]
    negative = [r for r in rows if not r['positive_state']]
    state = state_summary(rows)
    cluster = cluster_analysis(rows)
    trades = {str(c): trade_summary(positive, c) for c in spec['cost_roundtrip_bps']}
    curves = {str(c): portfolio(positive, frames, c) for c in spec['cost_roundtrip_bps']}
    groups = defaultdict(list)
    for r in positive:
        groups[r['month']].append(r)
    contributions = [max(0, sum(r['gross_bps'] - 60 for r in group)) for group in groups.values()]
    concentration = max(contributions) / sum(contributions) if sum(contributions) else 1.0
    gate = spec['development_screen']
    ci = cluster['descriptive_98pct_effect_interval_bps']
    checks = {
        'calendar_clusters': state['months'] >= gate['minimum_calendar_clusters'],
        'selected_trades': len(positive) >= gate['minimum_selected_trades'],
        'selected_symbols': len({r['symbol'] for r in positive}) >= gate['minimum_selected_symbols'],
        'both_states': min(len({r['month'] for r in positive}), len({r['month'] for r in negative})) >= gate['minimum_each_state_months'],
        'state_hurdle': state['effect_bps'] is not None and state['effect_bps'] > gate['primary_state_effect_hurdle_bps'],
        'state_interval': ci is not None and ci[0] > 0 and cluster['bootstrap_valid'] == 2000,
        'leave_symbol': all(v is not None and v > 0 for v in cluster['leave_one_symbol_out_effect_bps'].values()),
        'net60': trades['60']['net_gross_minus_cost_bps'] > 0,
        'portfolio60': curves['60']['return_pct'] > 0,
        'btc_excess': trades['60']['mean_excess_bps'] > 0,
        'unconditional_lift': trades['60']['net_gross_minus_cost_bps'] > trade_summary(rows, 60)['net_gross_minus_cost_bps'],
        'month_concentration': concentration <= gate['no_single_month_positive_net_contribution_share_above']}
    return {'state_primary': state, 'cluster': cluster, 'selected_cost_sensitivity': trades,
            'signals': len(positive), 'completed_trades': len(positive), 'overlap_skipped': 0, 'pending': 0,
            'entry_utc_hour_counts': {'0': len(positive)},
            'session_note': 'calendar-month UTC00 entries only; coarse Asia proxy, no session filter or watch',
            'equal_initial_sleeve_portfolios': curves, 'unconditional_reference40': trade_summary(rows, 40),
            'unconditional_portfolio40': portfolio(rows, frames, 40),
            'inverted_portfolio40': portfolio(negative, frames, 40),
            'inverted_reference40': trade_summary(negative, 40), 'controls': timing_controls(rows),
            'by_symbol_state': {s: state_summary([r for r in rows if r['symbol'] == s]) for s in SYMBOLS},
            'by_symbol_selected_reference40': {s: trade_summary([r for r in positive if r['symbol'] == s], 40) for s in SYMBOLS},
            'by_year_selected_reference40': {str(y): trade_summary([r for r in positive if r['year'] == y], 40) for y in sorted({r['year'] for r in rows})},
            'by_year_state': {str(y): state_summary([r for r in rows if r['year'] == y]) for y in sorted({r['year'] for r in rows})},
            'largest_month_positive_net60_contribution_share': concentration,
            'development_checks': checks, 'failed_checks': [k for k, v in checks.items() if not v],
            'disposition': 'DEVELOPMENT_INTERESTING_NOT_READY' if all(checks.values()) else 'REJECTED_AS_SPECIFIED',
            'observations': rows, 'verified_out_of_sample_evidence': False, 'candidate_frozen': False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    root = Path.cwd()
    config = root / 'config/public_monthly_momentum_state_v1.json'
    spec = json.loads(config.read_text())
    committed = subprocess.check_output(['git', 'show', '6c2a37f0ba091f557d61efa19e61ed38c966f610:config/public_monthly_momentum_state_v1.json'], cwd=root)
    if config.read_bytes() != committed:
        raise ValueError('study design changed after definition commit')
    manifest = json.loads((root / spec['source_manifest']).read_text())
    frames = {}
    for s in (spec['benchmark_symbol'], *spec['symbols']):
        path = root / spec['source_dir'] / (s + '.csv')
        if sha256_file(path) != manifest['symbols'][s.replace('_', '')]['aligned_csv_sha256']:
            raise ValueError('spent source hash mismatch')
        frames[s] = read_bars(path, 480, utc('2026-10-10T00:00:00Z'))
    rows = observations(frames)
    report = analyze(rows, frames, spec)
    report.update(study_id=spec['study_id'], candidate_id=spec['candidate_id'],
                  design_commit='6c2a37f0ba091f557d61efa19e61ed38c966f610', design_sha256=sha256_file(config),
                  source_sha256={s: sha256_file(root / spec['source_dir'] / (s + '.csv')) for s in frames},
                  source_first=iso(frames['BTC_USDT'][0].timestamp), source_last=iso(frames['BTC_USDT'][-1].timestamp),
                  first_entry=rows[0]['entry_time'], final_exit=rows[-1]['exit_time'],
                  trial_accounting=spec['trial_accounting'])
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with (args.output_dir / 'report.json').open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({k: v for k, v in report.items() if k in ('state_primary', 'selected_cost_sensitivity', 'disposition', 'failed_checks', 'first_entry', 'final_exit')}))


if __name__ == '__main__':
    main()
