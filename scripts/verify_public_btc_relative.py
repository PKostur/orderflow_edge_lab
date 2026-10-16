"""Independent calendar/feature/target and closed-form forecast reconciliation.

Does not import the study module or sklearn. Reads the retained CSV and recorded
forecasts; uses completed-label timestamps to select each training cohort.
"""
import argparse
import csv
import json
import math
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    symbols = ('ETH_USDT', 'SOL_USDT', 'LINK_USDT')
    data = {}
    for s in ('BTC_USDT', *symbols):
        with (Path('artifacts/public_spot_8h_20261010/aligned_csv') / (s + '.csv')).open(newline='') as stream:
            data[s] = {datetime.fromisoformat(r['timestamp'].replace('Z', '+00:00')): {k: float(r[k]) for k in ('open', 'close')}
                       for r in csv.DictReader(stream)}
    eligible = []
    hours = timedelta(hours=8)
    for t in sorted(data['BTC_USDT']):
        if t.weekday() != 0 or t.hour:
            continue
        dates = [t - hours - timedelta(days=i) for i in range(90, -1, -1)]
        entry, exit_ = t + hours, t + hours + timedelta(days=7)
        if dates[0] not in data['BTC_USDT'] or exit_ not in data['BTC_USDT']:
            continue
        btc = [math.log(data['BTC_USDT'][d]['close']) for d in dates]
        br = np.diff(btc)
        for s in symbols:
            alt = [math.log(data[s][d]['close']) for d in dates]
            ar = np.diff(alt)
            beta = sum((a - ar.mean()) * (b - br.mean()) for a, b in zip(ar, br)) / sum((b - br.mean()) ** 2 for b in br)
            btc30 = btc[-1] - btc[-31]
            extra = alt[-1] - alt[-31] - beta * btc30
            gross = data[s][exit_]['open'] / data[s][entry]['open'] - 1
            bgross = data['BTC_USDT'][exit_]['open'] / data['BTC_USDT'][entry]['open'] - 1
            eligible.append({'time': t, 'exit': exit_, 'symbol': s,
                             'x': [btc30, beta, float(s == 'ETH_USDT'), float(s == 'LINK_USDT')],
                             'extra': extra, 'y': (gross - bgross) * 10000})
    errors = {'feature_max_abs': 0., 'target_bps_max_abs': 0., 'prediction_bps_max_abs': 0.}
    compared = 0
    with (args.artifact_dir / 'forecasts.csv').open(newline='') as stream:
        recorded = list(csv.DictReader(stream))
    for i in range(0, len(recorded), 3):
        group = recorded[i:i + 3]
        t = datetime.fromisoformat(group[0]['forecast_time'].replace('Z', '+00:00'))
        available = [r for r in eligible if r['exit'] <= t]
        train = available[-104 * 3:]
        assert len(train) == 312 and len({r['time'] for r in train}) == 104
        current = [r for r in eligible if r['time'] == t]
        assert len(current) == 3
        for kind in ('baseline', 'extended'):
            x = np.array([r['x'] + ([r['extra']] if kind == 'extended' else []) for r in train])
            q = np.array([r['x'] + ([r['extra']] if kind == 'extended' else []) for r in current])
            y = np.array([r['y'] for r in train])
            avg, scale = x.mean(axis=0), x.std(axis=0)
            scale[scale == 0] = 1
            z = (x - avg) / scale
            coefficients = np.linalg.solve(z.T @ z + np.eye(z.shape[1]), z.T @ (y - y.mean()))
            predictions = (q - avg) / scale @ coefficients + y.mean()
            errors['prediction_bps_max_abs'] = max(errors['prediction_bps_max_abs'], max(abs(p - float(r[kind + '_bps'])) for p, r in zip(predictions, group)))
        for actual, record in zip(current, group):
            assert actual['symbol'] == record['symbol']
            values = actual['x'][:2] + [actual['extra']]
            keys = ('btc30_log_return', 'beta90', 'strength30')
            errors['feature_max_abs'] = max(errors['feature_max_abs'], max(abs(x - float(record[k])) for x, k in zip(values, keys)))
            errors['target_bps_max_abs'] = max(errors['target_bps_max_abs'], abs(actual['y'] - float(record['target_bps'])))
            compared += 1
    assert compared == 603 and all(e < 1e-6 for e in errors.values()), errors
    result = {'independent_reconciliation_passed': True, 'forecast_rows': compared, 'models_per_week': 2,
              'method': 'independent daily calendar/log-return calculation and closed-form ridge normal equations; no study/sklearn import',
              'absolute_tolerance': 1e-6, **errors}
    with args.output.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
