"""Separate offline volume-state and public minute-data feasibility studies.

Neither lane contains trading signals, account mutations or order transmission.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import platform
import re
import subprocess
import time
import urllib.error
import urllib.request
import zipfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import sklearn

from .btc_relative_state import fitted_model, model_record, write_csv, write_json
from .public_strategy_shadow import iso, read_bars, sha256_file, utc

SYMBOLS = ('ETH_USDT', 'SOL_USDT', 'LINK_USDT')
ALL = ('BTC_USDT', *SYMBOLS)
DAY = timedelta(days=1)
STEP = timedelta(hours=8)
SEED = 20261010


def verified_spec(root: Path, path: Path, commit: str) -> dict:
    resolved = subprocess.check_output(['git', 'rev-parse', '--verify', commit + '^{commit}'], cwd=root, text=True).strip()
    if len(commit) != 40 or resolved != commit:
        raise ValueError('full immutable design commit required')
    relative = path.resolve().relative_to(root.resolve()).as_posix()
    original = subprocess.check_output(['git', 'show', f'{commit}:{relative}'], cwd=root)
    if path.read_bytes() != original:
        raise ValueError('design differs from committed bytes')
    spec = json.loads(original)
    if tuple(spec['symbols']) != SYMBOLS or spec['schema_version'] != 1 or spec['order_transmission_supported']:
        raise ValueError('unsupported research-only design')
    return spec


def retained_frames(root: Path, spec: dict, commit: str) -> tuple[dict, dict]:
    path = root / spec['volume']['source_manifest']
    original = subprocess.check_output(['git', 'show', f'{commit}:{spec["volume"]["source_manifest"]}'], cwd=root)
    if path.read_bytes().replace(b'\r\n', b'\n') != original.replace(b'\r\n', b'\n'):
        raise ValueError('retained source manifest changed')
    manifest = json.loads(original)
    frames, hashes = {}, {}
    for s in ALL:
        entry = manifest['symbols'][s.replace('_', '')]
        for key, digest in [('raw_file', 'raw_sha256'), ('aligned_csv', 'aligned_csv_sha256')]:
            source = path.parent / entry[key]
            actual = sha256_file(source)
            if actual != entry[digest]:
                raise ValueError('retained source hash mismatch')
            hashes[source.relative_to(root).as_posix()] = actual
        frames[s] = read_bars(path.parent / entry['aligned_csv'], 480, utc('2026-10-10T00:00:00Z'))
        if len(frames[s]) != spec['volume']['source_bars']:
            raise ValueError('retained cohort changed')
    return frames, hashes


def volume_observations(frames: dict) -> list[list[dict]]:
    grid = [b.timestamp for b in frames['BTC_USDT']]
    if any([b.timestamp for b in frames[s]] != grid for s in SYMBOLS) or any(b - a != STEP for a, b in zip(grid, grid[1:])):
        raise ValueError('matching continuous 8h grids required')
    if any(t.utcoffset() != timedelta(0) or t.hour % 8 or t.minute or t.second or t.microsecond for t in grid):
        raise ValueError('UTC 8h alignment required')
    index = {t: i for i, t in enumerate(grid)}
    daily = {}
    for t in grid:
        i = index[t]
        if t.hour != 0 or i + 3 > len(grid):
            continue
        daily[t] = {s: {'rv': sum(math.log(b.close / b.open) ** 2 for b in frames[s][i:i + 3]),
                        'turnover': sum((b.high + b.low + b.close) / 3 * b.volume for b in frames[s][i:i + 3])}
                    for s in ALL}
    result = []
    for t in sorted(daily):
        past = [t - DAY * d for d in range(30, 0, -1)]
        if past[0] not in daily or t + DAY + STEP not in index:
            continue
        rows = []
        for s in SYMBOLS:
            variances = [daily[d][s]['rv'] for d in past]
            turnover = [daily[d][s]['turnover'] for d in past]
            if not all(math.isfinite(v) and v > 0 for v in turnover):
                raise ValueError('positive finite daily turnover required; no imputation')
            x = [math.log(variances[-1] + 1e-12), math.log(np.mean(variances[-7:]) + 1e-12),
                 math.log(np.mean(variances) + 1e-12), math.log(daily[past[-1]]['BTC_USDT']['rv'] + 1e-12),
                 float(s == 'ETH_USDT'), float(s == 'LINK_USDT')]
            i = index[t] + 1
            target = math.log(sum(math.log(b.close / b.open) ** 2 for b in frames[s][i:i + 3]) + 1e-12)
            monday = t - DAY * t.weekday()
            rows.append({'symbol': s, 'forecast_time': iso(t), 'target_start': iso(t + STEP),
                         'target_end': iso(t + DAY + STEP), 'year': t.year, 'week': iso(monday),
                         'x': x, 'volume_log_ratio': math.log(turnover[-1] / np.mean(turnover)), 'target': target})
        result.append(rows)
    if any(utc(b[0]['forecast_time']) - utc(a[0]['forecast_time']) != DAY for a, b in zip(result, result[1:])):
        raise ValueError('daily cohort discontinuity')
    return result


def volume_forecasts(days: list[list[dict]], training_days=730) -> tuple[list[dict], list[dict]]:
    out, records = [], []
    for i in range(training_days + 1, len(days)):
        first, stop = i - training_days - 1, i - 1
        train = [r for day in days[first:stop] for r in day]
        if len(train) != training_days * 3 or any(utc(r['target_end']) > utc(days[i][0]['forecast_time']) for r in train):
            raise ValueError('unavailable training label')
        x, y = [r['x'] for r in train], [r['target'] for r in train]
        base = fitted_model(x, y, 1)
        extended = fitted_model([r['x'] + [r['volume_log_ratio']] for r in train], y, 1)
        models = [model_record(base, 'baseline'), model_record(extended, 'extended')]
        b = base.predict([r['x'] for r in days[i]])
        e = extended.predict([r['x'] + [r['volume_log_ratio']] for r in days[i]])
        d = None
        if first > 0:
            delayed = fitted_model([days[j][k]['x'] + [days[j - 1][k]['volume_log_ratio']]
                                    for j in range(first, stop) for k in range(3)], y, 1)
            d = delayed.predict([r['x'] + [days[i - 1][k]['volume_log_ratio']] for k, r in enumerate(days[i])])
            models.append(model_record(delayed, 'delayed_control'))
        for k, r in enumerate(days[i]):
            out.append({**{key: value for key, value in r.items() if key != 'x'},
                        'baseline': float(b[k]), 'extended': float(e[k]), 'delayed': float(d[k]) if d is not None else None})
        # Shared helper labels the intercept bps; here explicitly correct its units.
        for model in models:
            model['intercept_log_proxy'] = model.pop('intercept_bps')
        records.append({'forecast_time': days[i][0]['forecast_time'], 'training_days': training_days,
                        'training_rows': len(train), 'first_training_forecast': train[0]['forecast_time'],
                        'last_training_forecast': train[-1]['forecast_time'], 'latest_training_label_end': train[-1]['target_end'],
                        'models': models})
    return out, records


def score(rows: list[dict], key='extended') -> dict:
    if not rows:
        return {'n': 0, 'mse_reduction': None}
    y, b, e = (np.array([r[k] for r in rows]) for k in ('target', 'baseline', key))
    mse_b, mse_e = float(np.mean((y - b) ** 2)), float(np.mean((y - e) ** 2))
    return {'n': len(rows), 'mse_reduction': 1 - mse_e / mse_b if mse_b > 0 else None,
            'baseline_mse_log_proxy_squared': mse_b, 'extended_mse_log_proxy_squared': mse_e,
            'baseline_mae_log_proxy': float(np.mean(abs(y - b))), 'extended_mae_log_proxy': float(np.mean(abs(y - e)))}


def volume_analysis(rows: list[dict]) -> dict:
    groups = defaultdict(list)
    for r in rows:
        groups[r['week']].append(r)
    keys = sorted(groups)
    sums = np.array([[sum((r['target'] - r[k]) ** 2 for r in groups[w]) for k in ('baseline', 'extended')] for w in keys])
    rng = np.random.default_rng(SEED)
    draws = []
    for _ in range(2000):
        ids = ((rng.integers(0, len(keys), (len(keys) + 3) // 4)[:, None] + np.arange(4)) % len(keys)).ravel()[:len(keys)]
        b, e = sums[ids].sum(axis=0)
        if b > 0:
            draws.append(1 - e / b)
    interval = np.quantile(draws, [.005, .995]).tolist() if draws else None
    primary = score(rows)
    symbols = {s: score([r for r in rows if r['symbol'] == s]) for s in SYMBOLS}
    years = {str(y): score([r for r in rows if r['year'] == y]) for y in sorted({r['year'] for r in rows})}
    leave_year = {str(y): score([r for r in rows if r['year'] != y]) for y in sorted({r['year'] for r in rows})}
    positive = lambda v: v is not None and v > 0
    checks = {'minimum_weeks': len(keys) >= 156, 'mse_hurdle': primary['mse_reduction'] is not None and primary['mse_reduction'] >= .01,
              'bootstrap_lower_positive': interval is not None and interval[0] > 0,
              'every_symbol_improves': all(positive(v['mse_reduction']) for v in symbols.values()),
              'two_complete_years_improve': sum(positive(years.get(str(y), {}).get('mse_reduction')) for y in (2023, 2024, 2025)) >= 2,
              'leave_year_improves': all(positive(v['mse_reduction']) for v in leave_year.values())}
    y, b, e = (np.array([r[k] for r in rows]).reshape(-1, 3) for k in ('target', 'baseline', 'extended'))
    year_values = np.array([rows[i]['year'] for i in range(0, len(rows), 3)])
    delta, denominator = e - b, float(np.sum((y - b) ** 2))
    rng = np.random.default_rng(SEED)
    placebo = []
    for _ in range(500):
        shuffled = delta.copy()
        for year in sorted(set(year_values)):
            ids = np.flatnonzero(year_values == year)
            full = len(ids) // 28 * 28
            blocks = ids[:full].reshape(-1, 28)
            shuffled[blocks.ravel()] = delta[blocks[rng.permutation(len(blocks))].ravel()]
        if denominator > 0:
            placebo.append(1 - float(np.sum((y - b - shuffled) ** 2)) / denominator)
    leave_week = [score([r for r in rows if r['week'] != w])['mse_reduction'] for w in keys]
    return {'primary': primary, 'shared_calendar_weeks': len(keys), 'by_symbol': symbols, 'by_year': years,
            'leave_year': leave_year, 'leave_symbol': {s: score([r for r in rows if r['symbol'] != s]) for s in SYMBOLS},
            'leave_week_mse_reduction_range': [min(x for x in leave_week if x is not None), max(x for x in leave_week if x is not None)]
            if any(x is not None for x in leave_week) else None,
            'descriptive_99pct_mse_reduction_interval': interval, 'bootstrap_replicates': 2000, 'bootstrap_valid': len(draws),
            'delayed': score([r for r in rows if r['delayed'] is not None], 'delayed'),
            'delayed_unavailable_rows': sum(r['delayed'] is None for r in rows),
            'placebo': {'n': 500, 'mean_mse_reduction': float(np.mean(placebo)) if placebo else None,
                        'descriptive_95pct_range': np.quantile(placebo, [.025, .975]).tolist() if placebo else None,
                        'fraction_at_least_observed': float(np.mean(np.array(placebo) >= primary['mse_reduction'])) if placebo and primary['mse_reduction'] is not None else None,
                        'fixed_tail_days_by_year': {str(v): int(np.sum(year_values == v) % 28) for v in sorted(set(year_values))},
                        'formal_p_value': False},
            'checks': checks, 'failed_checks': [k for k, v in checks.items() if not v],
            'disposition': 'DEVELOPMENT_STATE_INFORMATION_ONLY' if all(checks.values()) else 'REJECTED_AS_SPECIFIED',
            'economics': 'NOT_DESIGNED_NOT_RUN', 'trade_count': None, 'new_trading_cells': 0}


def request_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={'User-Agent': 'orderflow-edge-lab-public-research/1'})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read()
        except OSError as exc:
            if isinstance(exc, urllib.error.HTTPError) and exc.code not in (429, 500, 502, 503, 504):
                raise
            if attempt == 2:
                raise
            time.sleep(attempt + 1)
    raise RuntimeError('unreachable request state')


def validate_checksum(payload: bytes, checksum: bytes, filename: str) -> str:
    parts = checksum.decode('utf-8').split()
    if len(parts) != 2 or not re.fullmatch('[a-fA-F0-9]{64}', parts[0]) or parts[1].lstrip('*') != filename:
        raise ValueError('invalid archive checksum format/filename')
    digest = hashlib.sha256(payload).hexdigest()
    if digest != parts[0].lower():
        raise ValueError('archive checksum mismatch')
    return digest


def decode_archive(payload: bytes, day: str) -> list[dict]:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        files = archive.namelist()
        if len(files) != 1 or not files[0].endswith('.csv'):
            raise ValueError('exactly one CSV archive member required')
        if archive.getinfo(files[0]).file_size > 5_000_000:
            raise ValueError('unexpected daily archive size')
        text = archive.read(files[0]).decode('utf-8')
    rows = []
    expected = int(utc(day + 'T00:00:00Z').timestamp())
    multiplier = 1_000_000 if day >= '2025-01-01' else 1000
    for i, r in enumerate(csv.reader(io.StringIO(text))):
        if len(r) != 12 or int(r[0]) != (expected + i * 60) * multiplier or int(r[6]) != (expected + (i + 1) * 60) * multiplier - 1:
            raise ValueError('invalid minute schema/grid/units')
        o, h, l, c, v, q, n, tb, tq = [float(r[j]) for j in (1, 2, 3, 4, 5, 7, 8, 9, 10)]
        if (not all(math.isfinite(x) for x in (o, h, l, c, v, q, n, tb, tq)) or min(o, h, l, c) <= 0
                or min(v, q, n, tb, tq) < 0 or n != int(n) or h < max(o, c, l) or l > min(o, c, h)):
            raise ValueError('invalid minute OHLCV/trade count')
        rows.append({'time_s': expected + i * 60, 'open': o, 'close': c, 'volume': v, 'quote_volume': q, 'trades': int(n)})
    if len(rows) != 1440:
        raise ValueError('complete1440-minute UTC day required')
    return rows


def walk_book(book: dict, quote_notional=1000.) -> dict:
    def levels(key):
        values = [(float(p), float(q)) for p, q in book[key]]
        if not values or any(not math.isfinite(p) or not math.isfinite(q) or p <= 0 or q <= 0 for p, q in values):
            raise ValueError('invalid book levels')
        return values
    asks, bids = levels('asks'), levels('bids')
    if (any(b[0] <= a[0] for a, b in zip(asks, asks[1:]))
            or any(b[0] >= a[0] for a, b in zip(bids, bids[1:])) or asks[0][0] <= bids[0][0]):
        raise ValueError('unsorted or crossed book')
    remaining, base = quote_notional, 0.
    for price, quantity in asks:
        paid = min(remaining, price * quantity)
        base += paid / price
        remaining -= paid
    spread = (asks[0][0] - bids[0][0]) / ((asks[0][0] + bids[0][0]) / 2) * 10000
    if remaining > 1e-7:
        return {'status': 'DEPTH_GATE_FAILED', 'spread_bps': spread, 'insufficient_side': 'asks'}
    remaining, proceeds = base, 0.
    for price, quantity in bids:
        sold = min(remaining, quantity)
        proceeds += sold * price
        remaining -= sold
    if remaining > 1e-10:
        return {'status': 'DEPTH_GATE_FAILED', 'spread_bps': spread, 'insufficient_side': 'bids'}
    return {'status': 'CURRENT_BOOK_WALK_ONLY', 'spread_bps': spread,
            'loss_excluding_fees_bps': (1 - proceeds / quote_notional) * 10000, 'quote_notional': quote_notional}


def minute_assessment(output: Path, spec: dict) -> dict:
    raw = output / 'raw'
    raw.mkdir()
    archives, diagnostics, failures, books = [], [], [], {}
    def download(s, day):
            symbol = s.replace('_', '')
            name = f'{symbol}-1m-{day}.zip'
            url = f'https://data.binance.vision/data/spot/daily/klines/{symbol}/1m/{name}'
            requested = iso(datetime.now(timezone.utc))
            try:
                payload = request_bytes(url)
                receipt = iso(datetime.now(timezone.utc))
                (raw / name).write_bytes(payload)
                checksum = request_bytes(url + '.CHECKSUM')
                checksum_receipt = iso(datetime.now(timezone.utc))
                (raw / (name + '.CHECKSUM')).write_bytes(checksum)
                digest = validate_checksum(payload, checksum, name)
                parsed = decode_archive(payload, day)
                record = {'symbol': s, 'day': day, 'url': url, 'request_utc': requested, 'receipt_utc': receipt,
                                 'checksum_receipt_utc': checksum_receipt, 'sha256': digest,
                                 'checksum_sha256': hashlib.sha256(checksum).hexdigest(), 'bars': 1440,
                                 'timestamp_unit': 'us' if day >= '2025-01-01' else 'ms'}
                return parsed, record, None
            except (OSError, ValueError, zipfile.BadZipFile, csv.Error) as exc:
                return None, None, {'symbol': s, 'day': day, 'url': url, 'error': str(exc),
                                   'request_utc': requested, 'failure_observed_utc': iso(datetime.now(timezone.utc))}
    # Independent symbols have distinct raw paths; keep aggregation in fixed order.
    with ThreadPoolExecutor(max_workers=4) as executor:
      for day in spec['minute']['dates']:
        panel = {}
        for s, (parsed, record, failure) in zip(ALL, executor.map(lambda s: download(s, day), ALL)):
            if failure:
                failures.append(failure)
            else:
                panel[s] = parsed
                archives.append(record)
        if len(panel) == 4:
            br = np.diff(np.log([r['close'] for r in panel['BTC_USDT']]))
            for s in SYMBOLS:
                ar = np.diff(np.log([r['close'] for r in panel[s]]))
                magnitude = abs(np.expm1(ar)) * 10000
                corr = lambda x, y: float(np.corrcoef(x, y)[0, 1]) if np.std(x) > 0 and np.std(y) > 0 else None
                diagnostics.append({'symbol': s, 'day': day, 'returns': len(ar),
                                    'lag0_correlation': corr(br, ar), 'btc_leads_one_minute_correlation': corr(br[:-1], ar[1:]),
                                    'median_abs_move_bps': float(np.median(magnitude)),
                                    'p95_abs_move_bps': float(np.quantile(magnitude, .95)),
                                    'fraction_abs_move_above_60bps': float(np.mean(magnitude > 60)),
                                    'median_trade_count': float(np.median([r['trades'] for r in panel[s]]))})
        print('minute date checked', day, 'complete symbols', len(panel), flush=True)
    for s in ALL:
        url = f'https://api.binance.com/api/v3/depth?symbol={s.replace("_", "")}&limit=20'
        start = datetime.now(timezone.utc)
        try:
            payload = request_bytes(url)
            end = datetime.now(timezone.utc)
            (raw / (s + '-book.json')).write_bytes(payload)
            books[s] = {**walk_book(json.loads(payload)), 'url': url, 'request_utc': iso(start),
                        'receipt_utc': iso(end), 'request_duration_seconds': (end - start).total_seconds(),
                        'sha256': hashlib.sha256(payload).hexdigest(), 'historical_execution_calibration': False}
        except (OSError, ValueError, KeyError) as exc:
            books[s] = {'status': 'BOOK_UNAVAILABLE', 'error': str(exc), 'url': url}
    assessed = datetime.now(timezone.utc)
    for book in books.values():
        book['assessed_at_utc'] = iso(assessed)
        book['exchange_feed_age_known'] = False
        if 'receipt_utc' in book:
            book['local_receipt_age_seconds_at_assessment'] = (assessed - utc(book['receipt_utc'])).total_seconds()
    return {'archives': archives, 'archive_failures': failures,
            'data_access_passed': len(archives) == 48 and not failures,
            'bars_downloaded': len(archives) * 1440, 'sample_days': len(spec['minute']['dates']),
            'continuous_multi_year_history': False, 'diagnostics': diagnostics if not failures else [],
            'diagnostics_withheld_for_incomplete_panel': bool(failures), 'books': books,
            'disposition': 'SOURCE_ACCESS_FEASIBLE_EXECUTION_AND_PREDICTION_UNCONFIRMED' if not failures else 'BLOCKED_INCOMPLETE_SOURCE_PANEL',
            'economics': 'NOT_DESIGNED_NOT_RUN', 'trade_count': None, 'new_trading_cells': 0,
            'paper_replication': False, 'execution_gate': 'NOT_CONFIRMED_BY_CURRENT_SNAPSHOT'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lane', choices=('volume', 'minute'), required=True)
    parser.add_argument('--spec', type=Path, required=True)
    parser.add_argument('--design-commit', required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    root = Path.cwd().resolve()
    spec = verified_spec(root, args.spec.resolve(), args.design_commit)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    if args.lane == 'volume':
        frames, hashes = retained_frames(root, spec, args.design_commit)
        days = volume_observations(frames)
        rows, models = volume_forecasts(days, spec['volume']['training_days'])
        expected = spec['volume']
        if (len(rows) != expected['expected_rows'] or len(models) != expected['expected_days']
                or rows[0]['forecast_time'] != expected['first_forecast'] or rows[-1]['forecast_time'] != expected['last_forecast']):
            raise ValueError('unexpected forecast cohort; do not trim')
        result = volume_analysis(rows)
        result.update(source_sha256=hashes, source_first=iso(frames['BTC_USDT'][0].timestamp),
                      source_last=iso(frames['BTC_USDT'][-1].timestamp), first_forecast=rows[0]['forecast_time'],
                      last_forecast=rows[-1]['forecast_time'], final_target_end=rows[-1]['target_end'])
        write_csv(args.output_dir / 'forecasts.csv', rows)
        write_json(args.output_dir / 'training_models.json', models)
    else:
        result = minute_assessment(args.output_dir, spec)
    result.update(study_id=spec[args.lane]['study_id'], design_commit=args.design_commit,
                  spec_sha256=sha256_file(args.spec), implementation_sha256=sha256_file(Path(__file__)),
                  repository_head_at_run=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                  runtime={'python': platform.python_version(), 'numpy': np.__version__, 'sklearn': sklearn.__version__},
                  verified_out_of_sample_evidence=False, order_transmission_supported=False,
                  prospective_start_utc=None, trial_accounting=spec['trial_accounting'])
    result['output_sha256'] = {p.relative_to(args.output_dir).as_posix(): sha256_file(p)
                               for p in sorted(args.output_dir.rglob('*')) if p.is_file()}
    write_json(args.output_dir / 'report.json', result)
    print(json.dumps({k: result[k] for k in ('study_id', 'disposition', 'economics', 'trade_count')}))


if __name__ == '__main__':
    main()
