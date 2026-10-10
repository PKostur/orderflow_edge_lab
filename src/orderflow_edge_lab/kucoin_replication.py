"""Fixed descriptive venue replication of unchanged failed downside."""
import hashlib
import json
from pathlib import Path
from statistics import mean

from .failed_downside_replication import replay
from .public_strategy_development import (
    beta_sensitivity, btc_regime, by_field, clustered, path_metrics,
    portfolio_equity, row_metrics, shifted_control, week_block_placebo, week_key,
)
from .public_strategy_shadow import iso, read_bars, utc


def analyze(frames):
    results = [replay(s, frames[s], frames['BTC_USDT']) for s in sorted(frames) if s != 'BTC_USDT']
    events = sorted([e for result in results for e in result['events']], key=lambda e: (e['entry_time'], e['symbol']))
    rows = []
    for event in events:
        if event['status'] != 'completed':
            continue
        symbol = event['symbol']
        indices = {iso(b.timestamp): i for i, b in enumerate(frames[symbol])}
        start, stop = indices[event['entry_time']], indices[event['exit_time']]
        dt = utc(event['entry_time'])
        direction, volatility = btc_regime(frames['BTC_USDT'], start)
        rows.append({'symbol': symbol, 'entry_time': event['entry_time'], 'week': week_key(event['exit_time']),
                     'year': dt.year, 'month': dt.strftime('%Y-%m'), 'entry_utc_hour': dt.hour,
                     'btc_regime': direction, 'btc_volatility': volatility, 'gross_bps': event['gross_bps'],
                     'btc_gross_bps': event['btc_matched_net_bps'] + 20,
                     'excess_bps': event['excess_vs_btc_bps'],
                     **path_metrics(frames[symbol], start, stop, event['entry_open'], 20)})
    metrics = row_metrics(rows)
    metrics['extended_cost_stress_mean_net_bps'] = {str(c): mean(r['gross_bps'] - c for r in rows) for c in (20, 30, 40, 60, 80)}
    return {'signals': sum(r['signals_count'] for r in results),
            'overlap_skipped': sum(r['overlap_skipped'] for r in results),
            'pending': sum(e['status'] != 'completed' for e in events), 'metrics_reference_20bps': metrics,
            'cluster_descriptive_only': clustered(rows), 'beta_reference_20bps': beta_sensitivity(rows),
            'by_symbol_reference_20bps': by_field(rows, 'symbol'), 'by_year_reference_20bps': by_field(rows, 'year'),
            'by_month_reference_20bps': by_field(rows, 'month'), 'by_hour_reference_20bps': by_field(rows, 'entry_utc_hour'),
            'by_regime_reference_20bps': by_field(rows, 'btc_regime'),
            'by_volatility_reference_20bps': by_field(rows, 'btc_volatility'),
            'portfolio_reference_20bps': portfolio_equity(events, frames, ['ETH_USDT', 'SOL_USDT', 'LINK_USDT']),
            'controls_reference_20bps': {'shift_plus_7': shifted_control(rows, frames, 7, 2),
                                        'same_week_timing': week_block_placebo(rows, frames, 2)}, 'events': events}


def book_cost(book, notional=1000):
    """Displayed contemporaneous buy then sell cost, no latency or fee claim."""
    best_bid, best_ask = float(book['bids'][0][0]), float(book['asks'][0][0])
    if not 0 < best_bid <= best_ask:
        raise ValueError('crossed or invalid book')
    remaining, units = notional, 0.0
    for price, size in book['asks']:
        price, size = float(price), float(size)
        take = min(remaining / price, size)
        units += take
        remaining -= take * price
    if remaining > 1e-8:
        raise ValueError('insufficient displayed ask depth')
    remaining, proceeds = units, 0.0
    for price, size in book['bids']:
        take = min(remaining, float(size))
        proceeds += take * float(price)
        remaining -= take
    if remaining > 1e-8:
        raise ValueError('insufficient displayed bid depth')
    return {'notional_usdt': notional, 'book_time_ms': book['time'],
            'quoted_spread_bps': (best_ask / best_bid - 1) * 10000,
            'displayed_buy_then_sell_loss_bps_excluding_fees': (1 - proceeds / notional) * 10000}


def main():
    root = Path.cwd()
    folder = root / 'artifacts/public_kucoin_8h_20261010'
    design = root / 'config/public_kucoin_replication_v1.json'
    manifest = json.loads((folder / 'manifest.json').read_text())
    if not manifest['complete'] or hashlib.sha256(design.read_bytes()).hexdigest() != manifest['design_sha256']:
        raise ValueError('incomplete source or altered design')
    for request in manifest['requests']:
        if hashlib.sha256((folder / 'raw' / request['file']).read_bytes()).hexdigest() != request['sha256']:
            raise ValueError('raw provenance mismatch')
    frames = {}
    for symbol, meta in manifest['symbols'].items():
        name = symbol.replace('-', '_')
        path = folder / 'aligned_csv' / (name + '.csv')
        if hashlib.sha256(path.read_bytes()).hexdigest() != meta['csv_sha256']:
            raise ValueError('CSV provenance mismatch')
        frames[name] = read_bars(path, 480, utc('2026-10-10T00:00:00Z'))
    comparison = {}
    for symbol in frames:
        prior = read_bars(root / 'artifacts/public_spot_8h_20261010/aligned_csv' / (symbol + '.csv'), 480, utc('2026-10-10T00:00:00Z'))
        comparison[symbol] = [b for b in prior if frames[symbol][0].timestamp <= b.timestamp <= frames[symbol][-1].timestamp]
    result = {'study_id': manifest['study_id'], 'design_commit': manifest['design_commit'],
              'design_sha256': manifest['design_sha256'], 'kucoin': analyze(frames),
              'binance_matched_period_separate': analyze(comparison),
              'status': 'DESCRIPTIVE_ONLY_NO_PROMOTION', 'verified_out_of_sample_evidence': False,
              'execution_calibrated': False, 'candidate_frozen': False,
              'limitations': ['Shared calendar weeks across venues are not independent observations.',
                              'Cost, portfolio and beta fields explicitly labeled reference20 are hypothetical.',
                              'Bootstrap interval labels inherited from prior descriptive diagnostic are not a formal multiplicity correction.',
                              'OHLCV cannot identify high/low order or executable fills. No threshold search.']}
    result['current_books'] = {}
    for symbol in manifest['symbols']:
        book = json.loads((folder / 'raw' / (symbol + '-book.json')).read_text())['data']
        request = next(r for r in manifest['requests'] if r['file'] == symbol + '-book.json')
        try:
            depth = book_cost(book)
        except ValueError as error:
            depth = {'status': 'DEPTH_GATE_FAILED', 'reason': str(error), 'notional_usdt': 1000}
        result['current_books'][symbol] = {**depth,
            'age_at_receipt_seconds': utc(request['received_at_utc']).timestamp() - book['time'] / 1000,
            'interpretation': 'Single snapshot; potentially stale/cache affected; no historical or account-cost calibration.'}
    with (folder / 'replication.json').open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({venue: {k: v for k, v in result[venue].items() if k in ('signals', 'overlap_skipped', 'metrics_reference_20bps', 'cluster_descriptive_only', 'controls_reference_20bps')}
                      for venue in ('kucoin', 'binance_matched_period_separate')}))


if __name__ == '__main__':
    main()
