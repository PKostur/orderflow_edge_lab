"""Fixed, spent-data BTC-relative prediction experiment; no order path.

Features and completed labels have separate clocks. Prediction gates precede
the single conditional economics diagnostic. All inference is descriptive.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import subprocess
from datetime import timedelta
from pathlib import Path
from statistics import mean, median

import numpy as np
import sklearn
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .public_strategy_shadow import Bar, iso, read_bars, sha256_file, utc

SYMBOLS = ('ETH_USDT', 'SOL_USDT', 'LINK_USDT')
BENCHMARK = 'BTC_USDT'
STEP = timedelta(hours=8)
WEEK = timedelta(days=7)


def strength(closes: np.ndarray) -> tuple[float, float, float]:
    """91 daily closes, columns BTC then alt. OLS beta includes an intercept."""
    if closes.shape != (91, 2) or not np.isfinite(closes).all() or (closes <= 0).any():
        raise ValueError('91 finite positive paired daily closes required')
    returns = np.diff(np.log(closes), axis=0)
    btc = returns[:, 0] - returns[:, 0].mean()
    variance = float(btc @ btc)
    if variance <= 0:
        raise ValueError('zero BTC return variance')
    alt = returns[:, 1] - returns[:, 1].mean()
    beta = float(btc @ alt / variance)
    btc30, alt30 = np.log(closes[-1] / closes[-31])
    return beta, float(btc30), float(alt30 - beta * btc30)


def weekly_observations(frames: dict[str, list[Bar]]) -> list[list[dict]]:
    """Build causal features plus explicitly future labels, never fitted together."""
    grid = [b.timestamp for b in frames[BENCHMARK]]
    if not grid or any([b.timestamp for b in frames[s]] != grid for s in SYMBOLS):
        raise ValueError('identical complete grids required')
    if any(t.utcoffset() != timedelta(0) or t.minute or t.second or t.microsecond or t.hour % 8 for t in grid):
        raise ValueError('UTC 8h grid required')
    if any(b - a != STEP for a, b in zip(grid, grid[1:])):
        raise ValueError('8h continuity required')
    index = {t: i for i, t in enumerate(grid)}
    weeks = []
    for forecast in grid:
        if forecast.weekday() != 0 or forecast.hour != 0:
            continue
        formation = [forecast - STEP - timedelta(days=d) for d in range(90, -1, -1)]
        entry, exit_ = forecast + STEP, forecast + STEP + WEEK
        if formation[0] not in index or exit_ not in index:
            continue
        i, j = index[entry], index[exit_]
        btc_gross = (frames[BENCHMARK][j].open / frames[BENCHMARK][i].open - 1) * 10000
        rows = []
        for symbol in SYMBOLS:
            daily = np.array([[frames[BENCHMARK][index[t]].close, frames[symbol][index[t]].close]
                              for t in formation])
            beta, btc30, incremental = strength(daily)
            gross = (frames[symbol][j].open / frames[symbol][i].open - 1) * 10000
            rows.append({'symbol': symbol, 'forecast_time': iso(forecast), 'entry_time': iso(entry),
                         'exit_time': iso(exit_), 'year': forecast.year, 'entry_index': i, 'exit_index': j,
                         'feature_latest_close_time': iso(forecast), 'beta90': beta,
                         'btc30_log_return': btc30, 'strength30': incremental,
                         'gross_bps': gross, 'btc_gross_bps': btc_gross, 'target_bps': gross - btc_gross})
        weeks.append(rows)
    if any(utc(b[0]['forecast_time']) - utc(a[0]['forecast_time']) != WEEK for a, b in zip(weeks, weeks[1:])):
        raise ValueError('eligible weekly cohort discontinuity')
    return weeks


def xrow(row: dict, extra: float | None = None) -> list[float]:
    result = [row['btc30_log_return'], row['beta90'], float(row['symbol'] == 'ETH_USDT'),
              float(row['symbol'] == 'LINK_USDT')]
    return result if extra is None else result + [extra]


def fitted_model(x: list, y: list, alpha: float):
    if not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError('nonfinite training values')
    model = make_pipeline(StandardScaler(), Ridge(alpha=alpha, fit_intercept=True, solver='svd'))
    model.fit(x, y)
    return model


def model_record(model, name: str) -> dict:
    scaler, ridge = model.steps[0][1], model.steps[1][1]
    return {'name': name, 'scaler_mean': scaler.mean_.tolist(), 'scaler_scale': scaler.scale_.tolist(),
            'standardized_coefficients': ridge.coef_.tolist(), 'intercept_bps': float(ridge.intercept_)}


def rolling_forecasts(weeks: list[list[dict]], training_weeks: int = 104, alpha: float = 1.) -> tuple[list[dict], list[dict]]:
    forecasts, records = [], []
    for i in range(training_weeks + 1, len(weeks)):
        start, stop = i - training_weeks - 1, i - 1
        train = [r for week in weeks[start:stop] for r in week]
        current = weeks[i]
        now = utc(current[0]['forecast_time'])
        if len(train) != training_weeks * 3 or any(utc(r['exit_time']) > now for r in train):
            raise ValueError('training label unavailable at forecast time')
        y = [r['target_bps'] for r in train]
        baseline = fitted_model([xrow(r) for r in train], y, alpha)
        extended = fitted_model([xrow(r, r['strength30']) for r in train], y, alpha)
        models = [model_record(baseline, 'baseline'), model_record(extended, 'extended')]
        bpred = baseline.predict([xrow(r) for r in current])
        epred = extended.predict([xrow(r, r['strength30']) for r in current])
        dpred = None
        if start > 0:
            dx = [xrow(weeks[j][k], weeks[j - 1][k]['strength30'])
                  for j in range(start, stop) for k in range(3)]
            delayed = fitted_model(dx, y, alpha)
            dpred = delayed.predict([xrow(r, weeks[i - 1][k]['strength30']) for k, r in enumerate(current)])
            models.append(model_record(delayed, 'delayed_control'))
        for k, row in enumerate(current):
            forecasts.append({**row, 'baseline_bps': float(bpred[k]), 'extended_bps': float(epred[k]),
                              'delayed_bps': float(dpred[k]) if dpred is not None else None})
        records.append({'forecast_time': current[0]['forecast_time'],
                        'training_first_forecast': train[0]['forecast_time'],
                        'training_last_forecast': train[-1]['forecast_time'],
                        'latest_training_label_completed_at': train[-1]['exit_time'],
                        'training_weeks': training_weeks, 'training_rows': len(train), 'models': models})
    if not forecasts:
        raise ValueError('no eligible forecasts')
    return forecasts, records


def metrics(rows: list[dict], prediction: str = 'extended_bps') -> dict:
    if not rows:
        return {'n': 0, 'mse_reduction': None}
    y = np.array([r['target_bps'] for r in rows])
    b = np.array([r['baseline_bps'] for r in rows])
    p = np.array([r[prediction] for r in rows])
    baseline_mse, mse = float(np.mean((b - y) ** 2)), float(np.mean((p - y) ** 2))
    variance = float(np.sum((p - p.mean()) ** 2))
    slope = float((p - p.mean()) @ (y - y.mean()) / variance) if variance else None
    return {'n': len(rows), 'weeks': len({r['forecast_time'] for r in rows}),
            'baseline_mse_bps_squared': baseline_mse, 'mse_bps_squared': mse,
            'mse_reduction': 1 - mse / baseline_mse if baseline_mse > 0 else None,
            'mae_bps': float(np.mean(np.abs(p - y))), 'baseline_mae_bps': float(np.mean(np.abs(b - y))),
            'direction_accuracy': float(np.mean((p > 0) == (y > 0))),
            'baseline_direction_accuracy': float(np.mean((b > 0) == (y > 0))),
            'always_positive_accuracy': float(np.mean(y > 0)), 'calibration_slope': slope,
            'calibration_intercept_bps': float(y.mean() - slope * p.mean()) if slope is not None else None}


def forecast_matrix(rows: list[dict], key: str) -> np.ndarray:
    if len(rows) % 3 or any(tuple(r['symbol'] for r in rows[i:i + 3]) != SYMBOLS for i in range(0, len(rows), 3)):
        raise ValueError('shared-week symbol grouping required')
    return np.array([r[key] for r in rows], dtype=float).reshape(-1, 3)


def uncertainty(rows: list[dict], replicates: int = 2000, seed: int = 20261010) -> dict:
    y, b, p = (forecast_matrix(rows, k) for k in ('target_bps', 'baseline_bps', 'extended_bps'))
    eb, ep = np.sum((b - y) ** 2, axis=1), np.sum((p - y) ** 2, axis=1)
    rng = np.random.default_rng(seed)
    draws = []
    n = len(eb)
    for _ in range(replicates):
        starts = rng.integers(0, n, size=(n + 3) // 4)
        sample = ((starts[:, None] + np.arange(4)) % n).ravel()[:n]
        denominator = float(eb[sample].sum())
        if denominator > 0:
            draws.append(1 - float(ep[sample].sum()) / denominator)
    leave = [1 - float(ep.sum() - e) / float(eb.sum() - d) if eb.sum() - d > 0 else None
             for d, e in zip(eb, ep)]
    return {'replicates': replicates, 'valid': len(draws), 'seed': seed, 'block_weeks': 4,
            'descriptive_99pct_mse_reduction_interval': np.quantile(draws, [.005, .995]).tolist() if draws else None,
            'leave_one_week_out_mse_reduction_range': [min(x for x in leave if x is not None), max(x for x in leave if x is not None)]
            if any(x is not None for x in leave) else None}


def placebo_controls(rows: list[dict], replicates: int = 500, seed: int = 20261010) -> dict:
    y, b, p = (forecast_matrix(rows, k) for k in ('target_bps', 'baseline_bps', 'extended_bps'))
    delta = p - b
    years = np.array([rows[i]['year'] for i in range(0, len(rows), 3)])
    rng = np.random.default_rng(seed)
    denominator = float(np.sum((b - y) ** 2))
    scores = []
    tails = {}
    for year in sorted(set(years)):
        tails[str(year)] = int(np.sum(years == year) % 4)
    for _ in range(replicates):
        shuffled = delta.copy()
        for year in sorted(set(years)):
            ids = np.flatnonzero(years == year)
            full = len(ids) // 4 * 4
            blocks = ids[:full].reshape(-1, 4)
            order = rng.permutation(len(blocks))
            shuffled[blocks.ravel()] = delta[blocks[order].ravel()]
        if denominator > 0:
            scores.append(1 - float(np.sum((b + shuffled - y) ** 2)) / denominator)
    actual = metrics(rows)['mse_reduction']
    return {'replicates': replicates, 'seed': seed, 'fixed_tail_weeks_by_year': tails,
            'mean_mse_reduction': mean(scores) if scores else None,
            'descriptive_95pct_range': np.quantile(scores, [.025, .975]).tolist() if scores else None,
            'fraction_at_least_observed': mean(x >= actual for x in scores) if actual is not None and scores else None,
            'formal_p_value': False}


def state_assessment(rows: list[dict], spec: dict) -> dict:
    primary = metrics(rows)
    clusters = uncertainty(rows, spec['bootstrap']['replicates'], spec['bootstrap']['seed'])
    symbols = {s: metrics([r for r in rows if r['symbol'] == s]) for s in SYMBOLS}
    years = {str(y): metrics([r for r in rows if r['year'] == y]) for y in sorted({r['year'] for r in rows})}
    leave_year = {str(y): metrics([r for r in rows if r['year'] != y]) for y in sorted({r['year'] for r in rows})}
    gate = spec['state_gates']
    interval = clusters['descriptive_99pct_mse_reduction_interval']
    positive = lambda x: x is not None and x > 0
    checks = {'minimum_weeks': primary['weeks'] >= gate['minimum_weeks'],
              'three_symbols': len(symbols) == gate['minimum_symbols'],
              'mse_reduction_hurdle': primary['mse_reduction'] is not None and primary['mse_reduction'] >= gate['minimum_mse_reduction'],
              'bootstrap_lower_positive': interval is not None and interval[0] > 0,
              'each_symbol_improves': all(positive(v['mse_reduction']) for v in symbols.values()),
              'complete_years_improve': sum(positive(years.get(str(y), {}).get('mse_reduction')) for y in gate['complete_years']) >= gate['minimum_complete_years_improved'],
              'leave_each_year_improves': all(positive(v['mse_reduction']) for v in leave_year.values())}
    delayed = [r for r in rows if r['delayed_bps'] is not None]
    return {'primary': primary, 'clusters': clusters, 'by_symbol': symbols, 'by_year': years,
            'leave_one_year_out': leave_year, 'leave_one_symbol_out': {s: metrics([r for r in rows if r['symbol'] != s]) for s in SYMBOLS},
            'controls': {'delayed': metrics(delayed, 'delayed_bps'), 'delayed_unavailable_rows': len(rows) - len(delayed),
                         'placebo': placebo_controls(rows, spec['controls']['placebo_replicates'], spec['controls']['seed'])},
            'checks': checks, 'failed_checks': [k for k, v in checks.items() if not v], 'passed': all(checks.values())}


def net_bps(gross: float, cost: float) -> float:
    if not np.isfinite([gross, cost]).all() or gross <= -10000 or not 0 <= cost < 20000:
        raise ValueError('invalid gross return/cost')
    return ((1 + gross / 10000) * (1 - cost / 20000) ** 2 - 1) * 10000


def excursions(row: dict, frames: dict[str, list[Bar]]) -> dict:
    bars = frames[row['symbol']]
    i, j = row['entry_index'], row['exit_index']
    held = bars[i:j]
    price = bars[i].open
    high_index = max(range(i, j), key=lambda k: bars[k].high)
    prior = bars[i:high_index]
    return {'mfe_bps': (max(b.high for b in held) / price - 1) * 10000,
            'mae_bps': (min(b.low for b in held) / price - 1) * 10000,
            'mae_before_mfe_bps': (min(b.low for b in prior) / price - 1) * 10000 if prior else None,
            'mfe_bar_offset': high_index - i, 'held_bars': len(held), 'intrabar_order_known': False}


def portfolio(selected: list[dict], cohort: list[dict], frames: dict[str, list[Bar]], cost: float, btc: bool = False) -> dict:
    starts = {(r['symbol'], r['entry_index']) for r in selected}
    ends = {(r['symbol'], r['exit_index']) for r in selected}
    if len(starts) != len(selected) or len(ends) != len(selected):
        raise ValueError('duplicate trades')
    balances = {s: 1.0 for s in SYMBOLS}
    active = {s: False for s in SYMBOLS}
    factor = 1 - cost / 20000
    first, last = min(r['entry_index'] for r in cohort), max(r['exit_index'] for r in cohort)
    curve = [{'time': iso(frames[BENCHMARK][first].timestamp), 'equity': 1.0}]
    peak, dd = 1., 0.
    for i in range(first, last + 1):
        for s in SYMBOLS:
            if (s, i) in ends:
                if not active[s]:
                    raise ValueError('exit without entry')
                balances[s] *= factor
                active[s] = False
            if (s, i) in starts:
                if active[s]:
                    raise ValueError('overlapping trades')
                balances[s] *= factor
                active[s] = True
        value = mean(balances.values())
        peak = max(peak, value)
        dd = min(dd, value / peak - 1)
        curve.append({'time': iso(frames[BENCHMARK][i].timestamp), 'equity': value})
        if i < last:
            for s in SYMBOLS:
                if active[s]:
                    bars = frames[BENCHMARK if btc else s]
                    balances[s] *= bars[i + 1].open / bars[i].open
    if any(active.values()):
        raise ValueError('unclosed portfolio')
    return {'return_pct': (curve[-1]['equity'] - 1) * 100, 'max_drawdown_pct': dd * 100,
            'drawdown_sampling': '8h opens and post-fill equity; not intrabar lows',
            'per_sleeve_return_pct': {s: (balances[s] - 1) * 100 for s in SYMBOLS},
            'cost_bps': cost, 'btc_on_candidate_schedule': btc, 'curve': curve}


def trade_metrics(rows: list[dict], cost: float) -> dict:
    if not rows:
        return {'n': 0, 'mean_net_bps': None, 'mean_matched_btc_net_excess_bps': None}
    net = [net_bps(r['gross_bps'], cost) for r in rows]
    excess = [net_bps(r['gross_bps'], cost) - net_bps(r['btc_gross_bps'], cost) for r in rows]
    wins, losses = sum(x for x in net if x > 0), -sum(x for x in net if x < 0)
    return {'n': len(rows), 'active_weeks': len({r['forecast_time'] for r in rows}),
            'mean_gross_bps': mean(r['gross_bps'] for r in rows), 'mean_net_bps': mean(net),
            'mean_matched_btc_net_excess_bps': mean(excess), 'median_net_bps': median(net),
            'win_rate': mean(x > 0 for x in net), 'profit_factor': wins / losses if losses else None,
            'worst_net_bps': min(net), 'best_net_bps': max(net),
            'mean_mfe_bps': mean(r['mfe_bps'] for r in rows), 'mean_mae_bps': mean(r['mae_bps'] for r in rows)}


def trading_robustness(selected: list[dict], cohort: list[dict], cost: float, seed: int = 20261010) -> dict:
    keys = sorted({r['forecast_time'] for r in cohort})
    groups = {k: [r for r in selected if r['forecast_time'] == k] for k in keys}
    rng = np.random.default_rng(seed)
    draws = []
    for _ in range(2000):
        sample_ids = ((rng.integers(0, len(keys), (len(keys) + 3) // 4)[:, None] + np.arange(4)) % len(keys)).ravel()[:len(keys)]
        sample = [r for i in sample_ids for r in groups[keys[i]]]
        if sample:
            draws.append(mean(net_bps(r['gross_bps'], cost) for r in sample))
    positive_week_pnl = [sum(max(0, net_bps(r['gross_bps'], cost)) for r in groups[k]) for k in keys]
    total = sum(positive_week_pnl)
    return {'all_calendar_clusters': len(keys), 'active_clusters': sum(bool(groups[k]) for k in keys),
            'descriptive_99pct_net_mean_interval_bps': np.quantile(draws, [.005, .995]).tolist() if draws else None,
            'largest_week_positive_event_return_share': max(positive_week_pnl) / total if total else None,
            'leave_one_week_out': {k: trade_metrics([r for r in selected if r['forecast_time'] != k], cost) for k in keys},
            'leave_one_symbol_out': {s: trade_metrics([r for r in selected if r['symbol'] != s], cost) for s in SYMBOLS},
            'by_year': {str(y): trade_metrics([r for r in selected if r['year'] == y], cost) for y in sorted({r['year'] for r in cohort})}}


def economic_assessment(rows: list[dict], frames: dict[str, list[Bar]], spec: dict) -> tuple[dict, list[dict], dict]:
    definition = spec['economics']
    primary_cost = definition['primary_cost_bps']
    selected = [{**r, **excursions(r, frames), 'entry_cost_factor': 1 - primary_cost / 20000,
                 'exit_cost_factor': 1 - primary_cost / 20000, 'primary_cost_bps': primary_cost,
                 'net_primary_cost_bps': net_bps(r['gross_bps'], primary_cost),
                 'matched_btc_net_primary_cost_bps': net_bps(r['btc_gross_bps'], primary_cost)}
                for r in rows if r['extended_bps'] > definition['signal_threshold_bps']]
    baseline = [r for r in rows if r['baseline_bps'] > definition['signal_threshold_bps']]
    curves, sensitivity = {}, {}
    for cost in definition['roundtrip_cost_bps']:
        port = portfolio(selected, rows, frames, cost)
        curves[str(cost)] = port.pop('curve')
        sensitivity[str(cost)] = {'trades': trade_metrics(selected, cost), 'portfolio': port}
    cost = definition['primary_cost_bps']
    primary = sensitivity[str(cost)]
    comparators = {}
    for name, trades, btc in [('baseline', baseline, False), ('unconditional', rows, False), ('matched_btc', selected, True)]:
        result = portfolio(trades, rows, frames, cost, btc)
        curves[name] = result.pop('curve')
        comparators[name] = result
    per_symbol = {s: trade_metrics([r for r in selected if r['symbol'] == s], cost) for s in SYMBOLS}
    ret, trades = primary['portfolio']['return_pct'], primary['trades']
    checks = {'minimum_trades': len(selected) >= definition['minimum_trades'],
              'minimum_active_weeks': len({r['forecast_time'] for r in selected}) >= definition['minimum_active_weeks'],
              'minimum_each_symbol': all(v['n'] >= definition['minimum_trades_each_symbol'] for v in per_symbol.values()),
              'positive_compounded_growth': ret > 0,
              'beats_all_comparators': all(ret > v['return_pct'] for v in comparators.values()),
              'positive_net_mean': trades['mean_net_bps'] is not None and trades['mean_net_bps'] > 0,
              'matched_btc_excess_hurdle': trades['mean_matched_btc_net_excess_bps'] is not None and trades['mean_matched_btc_net_excess_bps'] > definition['minimum_mean_matched_btc_net_excess_bps']}
    result = {'status': 'RUN', 'checks': checks, 'failed_checks': [k for k, v in checks.items() if not v],
              'passed': all(checks.values()), 'cost_sensitivity': sensitivity, 'comparators_at_60bps': comparators,
              'by_symbol_at_60bps': per_symbol, 'robustness_at_60bps': trading_robustness(selected, rows, cost),
              'exposure_fraction_symbol_weeks': len(selected) / len(rows),
              'session': {'entry_utc_hour': 8, 'entry_weekday': 'Monday', 'session_effect_identified': False},
              'costs_are_stress_assumptions': True, 'intrabar_order_known': False}
    return result, selected, curves


def analyze(rows: list[dict], frames: dict[str, list[Bar]], spec: dict) -> tuple[dict, list[dict], dict]:
    state = state_assessment(rows, spec)
    trades, curves = [], {}
    economics = {'status': 'NOT_RUN', 'reason': 'state gate failed; no trading outcome calculated'}
    if state['passed']:
        economics, trades, curves = economic_assessment(rows, frames, spec)
    survives = state['passed'] and economics.get('passed', False)
    return {'state': state, 'economics': economics,
            'disposition': 'DEVELOPMENT_INTERESTING_NOT_READY' if survives else 'REJECTED_AS_SPECIFIED',
            'verified_out_of_sample_evidence': False, 'candidate_frozen': False, 'order_transmission_supported': False,
            'trade_count': len(trades) if state['passed'] else None,
            'trading_cells_executed': int(state['passed']),
            'next_step': 'separate independent venue/cost/power/unseen-confirmation design' if survives
            else 'close this definition without retuning; a new question requires a new identifier'}, trades, curves


def load_verified(root: Path, spec_path: Path, design_commit: str) -> tuple[dict, dict[str, list[Bar]], dict]:
    relative = spec_path.resolve().relative_to(root.resolve()).as_posix()
    commit = subprocess.check_output(['git', 'rev-parse', '--verify', design_commit + '^{commit}'], cwd=root, text=True).strip()
    if len(design_commit) != 40 or commit != design_commit:
        raise ValueError('full immutable design commit required')
    committed = subprocess.check_output(['git', 'show', f'{commit}:{relative}'], cwd=root)
    if spec_path.read_bytes() != committed:
        raise ValueError('specification differs from design commit')
    spec = json.loads(committed)
    if spec['study_id'] != 'PSR4-BTC-RELATIVE-STRENGTH' or tuple(spec['symbols']) != SYMBOLS or spec['benchmark_symbol'] != BENCHMARK:
        raise ValueError('unsupported fixed study')
    manifest_path = root / spec['source_manifest']
    frozen_manifest = subprocess.check_output(['git', 'show', f'{commit}:{spec["source_manifest"]}'], cwd=root)
    # This legacy JSON is text in Git and may be checked out as CRLF on Windows.
    # Permit only that transport transformation; raw and CSV hashes remain exact.
    if manifest_path.read_bytes().replace(b'\r\n', b'\n') != frozen_manifest.replace(b'\r\n', b'\n'):
        raise ValueError('source manifest changed since design commit')
    manifest = json.loads(frozen_manifest)
    hashes, frames = {}, {}
    for s in (BENCHMARK, *SYMBOLS):
        entry = manifest['symbols'][s.replace('_', '')]
        for key, expected in [('aligned_csv', 'aligned_csv_sha256'), ('raw_file', 'raw_sha256')]:
            path = manifest_path.parent / entry[key]
            hashes[str(path.relative_to(root).as_posix())] = sha256_file(path)
            if hashes[str(path.relative_to(root).as_posix())] != entry[expected]:
                raise ValueError('source hash mismatch: ' + str(path))
        frames[s] = read_bars(manifest_path.parent / entry['aligned_csv'], 480, utc(spec['source_as_of']))
        if len(frames[s]) != spec['source_bars'] or iso(frames[s][0].timestamp) != spec['source_first'] or iso(frames[s][-1].timestamp) != spec['source_last']:
            raise ValueError('unexpected source cohort')
    return spec, frames, {'source_sha256': hashes, 'source_manifest_sha256': sha256_file(manifest_path),
                          'design_manifest_git_blob_sha256': hashlib.sha256(frozen_manifest).hexdigest(),
                          'design_sha256': sha256_file(spec_path), 'design_commit': commit}


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open('x', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, value) -> None:
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec', type=Path, required=True)
    parser.add_argument('--design-commit', required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    root = Path.cwd().resolve()
    spec, frames, provenance = load_verified(root, args.spec.resolve(), args.design_commit)
    weeks = weekly_observations(frames)
    rows, models = rolling_forecasts(weeks, spec['model']['training_weeks'], spec['model']['alpha'])
    expected = spec['expected_forecast_cohort']
    if (len(rows) != expected['rows'] or len(models) != expected['weeks']
            or rows[0]['forecast_time'] != expected['first_forecast'] or rows[-1]['forecast_time'] != expected['last_forecast']
            or rows[-1]['exit_time'] != expected['final_exit']):
        raise ValueError('unexpected forecast cohort; do not silently trim')
    report, trades, curves = analyze(rows, frames, spec)
    report.update(provenance, study_id=spec['study_id'], candidate_id=spec['candidate_id'],
                  source_first=spec['source_first'], source_last=spec['source_last'], source_bars=spec['source_bars'],
                  forecast_cohort=expected, first_entry=rows[0]['entry_time'], final_exit=rows[-1]['exit_time'],
                  trial_accounting=spec['trial_accounting'],
                  implementation_sha256=sha256_file(Path(__file__)),
                  runtime={'python': platform.python_version(), 'numpy': np.__version__, 'sklearn': sklearn.__version__},
                  repository_head_at_run=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip(),
                  repository_dirty_at_run=bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=root)))
    args.output_dir.mkdir(parents=True, exist_ok=False)
    write_csv(args.output_dir / 'forecasts.csv', rows)
    write_json(args.output_dir / 'training_models.json', models)
    if trades:
        write_csv(args.output_dir / 'trades.csv', trades)
    if curves:
        write_json(args.output_dir / 'capital_curves.json', curves)
    report['output_sha256'] = {p.name: sha256_file(p) for p in sorted(args.output_dir.iterdir())}
    write_json(args.output_dir / 'report.json', report)
    digest = hashlib.sha256((args.output_dir / 'report.json').read_bytes()).hexdigest()
    print(json.dumps({'disposition': report['disposition'], 'state_primary': report['state']['primary'],
                      'failed_checks': report['state']['failed_checks'], 'economics': report['economics']['status'],
                      'report_sha256': digest}))


if __name__ == '__main__':
    main()
