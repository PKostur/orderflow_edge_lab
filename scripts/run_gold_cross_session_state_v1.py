from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd


def clean(v):
    if isinstance(v, (float, np.floating)):
        x = float(v)
        return x if math.isfinite(x) else None
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, dict):
        return {str(k): clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [clean(x) for x in v]
    return v


def rho(a, b) -> float:
    a = pd.Series(a, dtype=float)
    b = pd.Series(b, dtype=float)
    m = a.notna() & b.notna() & np.isfinite(a) & np.isfinite(b)
    if int(m.sum()) < 5:
        return float('nan')
    return float(a[m].rank(method='average').corr(b[m].rank(method='average')))


def stable_seed(base: int, text: str) -> int:
    h = hashlib.sha256(text.encode('utf-8')).digest()
    return int((base + int.from_bytes(h[:4], 'big')) % (2**32 - 1))


def sign_flip_pvalue(values: list[float], epochs: int, seed: int) -> float:
    x = np.asarray(values, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) == 0:
        return float('nan')
    obs = float(np.median(x))
    if obs <= 0:
        return 1.0
    rng = np.random.default_rng(seed)
    ax = np.abs(x)
    count = 0
    done = 0
    while done < epochs:
        n = min(2000, epochs - done)
        signs = rng.choice(np.array([-1.0, 1.0]), size=(n, len(ax)))
        null = np.median(signs * ax[None, :], axis=1)
        count += int(np.sum(null >= obs))
        done += n
    return float((count + 1) / (epochs + 1))


def bh_qvalues(pvals: list[float]) -> list[float]:
    p = np.asarray(pvals, dtype=float)
    q = np.full(len(p), np.nan, dtype=float)
    valid = np.where(np.isfinite(p))[0]
    if len(valid) == 0:
        return q.tolist()
    order = valid[np.argsort(p[valid])]
    m = len(order)
    raw = np.empty(m, dtype=float)
    for rank, idx in enumerate(order, start=1):
        raw[rank - 1] = p[idx] * m / rank
    adj = np.minimum.accumulate(raw[::-1])[::-1]
    adj = np.minimum(adj, 1.0)
    for j, idx in enumerate(order):
        q[idx] = adj[j]
    return q.tolist()


def parse_hhmm(text: str) -> int:
    h, m = map(int, text.split(':'))
    return h * 60 + m


def load_m15(path: Path, cfg: dict) -> pd.DataFrame:
    d = pd.read_csv(path)
    d.columns = [str(c).strip().lower() for c in d.columns]
    req = ['time', 'open', 'high', 'low', 'close', 'tick_volume']
    missing = [c for c in req if c not in d.columns]
    if missing:
        raise ValueError(f'{path}: missing {missing}')
    d['time'] = pd.to_datetime(d['time'], utc=True, errors='coerce')
    for c in req[1:]:
        d[c] = pd.to_numeric(d[c], errors='coerce')
    d = d.dropna(subset=req)
    d = d[(d[['open', 'high', 'low', 'close']] > 0).all(axis=1)]
    d = d[d['tick_volume'] >= int(cfg['data_admission']['minimum_tick_volume'])]
    d = d[d['time'].dt.weekday <= 4]
    d = d.drop_duplicates('time', keep='last').set_index('time').sort_index()
    return d[['open', 'high', 'low', 'close', 'tick_volume']]


def session_row(day_frame: pd.DataFrame, name: str, scfg: dict, min_fraction: float):
    start_min = parse_hhmm(scfg['start'])
    end_min = parse_hhmm(scfg['end_exclusive'])
    minutes = day_frame.index.hour * 60 + day_frame.index.minute
    g = day_frame[(minutes >= start_min) & (minutes < end_min)]
    expected = int(scfg['expected_m15_bars'])
    if g.empty or len(g) < math.ceil(expected * min_fraction):
        return None
    day = day_frame.index[0].floor('D')
    first_ts = day + pd.Timedelta(minutes=start_min)
    last_ts = day + pd.Timedelta(minutes=end_min - 15)
    if first_ts not in g.index or last_ts not in g.index:
        return None
    ret = float(math.log(float(g.loc[last_ts, 'close']) / float(g.loc[first_ts, 'open'])))
    return {
        f'{name}_return': ret,
        f'{name}_bars': int(len(g)),
        f'{name}_open': float(g.loc[first_ts, 'open']),
        f'{name}_close': float(g.loc[last_ts, 'close']),
    }


def build_daily_sessions(d: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    rows = []
    min_fraction = float(cfg['data_admission']['minimum_fraction_expected_bars_per_session'])
    for day, g in d.groupby(d.index.floor('D')):
        row = {'date': day}
        ok = True
        for name, scfg in cfg['sessions_utc'].items():
            if name == 'note':
                continue
            s = session_row(g, name, scfg, min_fraction)
            if s is None:
                ok = False
                break
            row.update(s)
        if not ok:
            continue
        row['pre_us_return'] = float(math.log(row['europe_close'] / row['asia_open']))
        rows.append(row)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).set_index('date').sort_index()


def relation_frame(sessions: pd.DataFrame, rel: dict) -> pd.DataFrame:
    name = rel['name']
    if name == 'asia_to_europe':
        out = pd.DataFrame({'source': sessions['asia_return'], 'target': sessions['europe_return']}, index=sessions.index)
    elif name == 'asia_to_us':
        out = pd.DataFrame({'source': sessions['asia_return'], 'target': sessions['us_liquid_return']}, index=sessions.index)
    elif name == 'europe_to_us':
        out = pd.DataFrame({'source': sessions['europe_return'], 'target': sessions['us_liquid_return']}, index=sessions.index)
    elif name == 'pre_us_to_us':
        out = pd.DataFrame({'source': sessions['pre_us_return'], 'target': sessions['us_liquid_return']}, index=sessions.index)
    elif name == 'previous_us_to_asia':
        out = pd.DataFrame({'source': sessions['us_liquid_return'].shift(1), 'target': sessions['asia_return']}, index=sessions.index)
    else:
        raise ValueError(name)
    return out.dropna()


def evaluate_hypothesis(frame: pd.DataFrame, relation: str, direction: str, start: pd.Timestamp, cfg: dict) -> dict:
    hid = f'{relation}__{direction}'
    predictor = frame['source'].to_numpy(float) * (1.0 if direction == 'momentum' else -1.0)
    target = frame['target'].to_numpy(float)
    cluster_days = int(cfg['state_first']['dependence_cluster_calendar_days'])
    folds = np.floor((frame.index - start) / pd.Timedelta(days=cluster_days)).astype(int)
    tmp = pd.DataFrame({'predictor': predictor, 'target': target, 'fold': folds}, index=frame.index)
    min_events = int(cfg['state_first']['minimum_events_per_fold'])
    fold_rows = []
    for fid, g in tmp.groupby('fold'):
        if len(g) < min_events:
            continue
        r = rho(g['predictor'], g['target'])
        if not np.isfinite(r):
            continue
        fold_rows.append({'fold': int(fid), 'events': int(len(g)), 'rho': float(r), 'mean_target_bps': float(g['target'].mean() * 10000.0)})
    rhos = [x['rho'] for x in fold_rows]
    year_rows = []
    for year, g in tmp.groupby(tmp.index.year):
        if len(g) < 30:
            continue
        r = rho(g['predictor'], g['target'])
        if np.isfinite(r):
            year_rows.append({'year': int(year), 'events': int(len(g)), 'rho': float(r)})
    return {
        'hypothesis_id': hid,
        'relation': relation,
        'direction': direction,
        'events': int(len(tmp)),
        'raw_source_target_spearman': float(rho(frame['source'], frame['target'])),
        'state_folds': int(len(fold_rows)),
        'folds': fold_rows,
        'median_fold_spearman': float(np.median(rhos)) if rhos else np.nan,
        'positive_fold_fraction': float(np.mean(np.asarray(rhos) > 0)) if rhos else 0.0,
        'sign_flip_p': sign_flip_pvalue(rhos, int(cfg['state_first']['sign_flip_epochs']), stable_seed(int(cfg['state_first']['sign_flip_seed']), hid)),
        'years_scorable': int(len(year_rows)),
        'positive_year_fraction': float(np.mean(np.asarray([x['rho'] for x in year_rows]) > 0)) if year_rows else 0.0,
        'years': year_rows,
        'target_mean_bps': float(frame['target'].mean() * 10000.0),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', required=True)
    ap.add_argument('--data', required=True)
    ap.add_argument('--output', required=True)
    args = ap.parse_args()
    cfg = json.loads(Path(args.config).read_text(encoding='utf-8'))
    raw = load_m15(Path(args.data), cfg)
    dev = cfg['periods']['development']
    start = pd.Timestamp(dev['start'], tz='UTC')
    end = pd.Timestamp(dev['end_exclusive'], tz='UTC')
    d = raw.loc[(raw.index >= start) & (raw.index < end)].copy()
    sessions = build_daily_sessions(d, cfg)
    if len(sessions) < 1000:
        raise SystemExit(f'insufficient admitted development days: {len(sessions)}')

    by_year = sessions.groupby(sessions.index.year).size().to_dict()
    hypotheses = []
    for rel in cfg['relations']:
        f = relation_frame(sessions, rel)
        for direction in cfg['directions']:
            hypotheses.append(evaluate_hypothesis(f, str(rel['name']), str(direction), start, cfg))
    if len(hypotheses) != int(cfg['state_first']['unique_hypotheses']):
        raise AssertionError('hypothesis count differs from frozen protocol')

    qvals = bh_qvalues([x.get('sign_flip_p', np.nan) for x in hypotheses])
    sf = cfg['state_first']
    for x, q in zip(hypotheses, qvals):
        x['bh_fdr_q'] = q
        x['state_pass'] = bool(
            x.get('state_folds', 0) >= int(sf['minimum_scorable_folds'])
            and x.get('median_fold_spearman', -np.inf) >= float(sf['minimum_median_fold_spearman'])
            and x.get('positive_fold_fraction', 0.0) >= float(sf['minimum_positive_spearman_fold_fraction'])
            and x.get('bh_fdr_q', 1.0) <= float(sf['maximum_bh_fdr_q'])
        )
    passed = [x for x in hypotheses if x.get('state_pass')]
    passed.sort(key=lambda x: (float(x.get('bh_fdr_q', 1.0)), -float(x.get('median_fold_spearman', -np.inf)), -float(x.get('positive_fold_fraction', 0.0)), -float(x.get('positive_year_fraction', 0.0)), x['hypothesis_id']))
    selected = passed[: int(sf['maximum_state_relations_to_freeze'])]

    payload = {
        'schema_version': 1,
        'protocol': cfg['protocol_name'],
        'evidence_class': cfg['evidence_class'],
        'development_period': dev,
        'data_integrity': {
            'raw_m15_rows_all_source': int(len(raw)),
            'development_m15_rows': int(len(d)),
            'development_first_bar': str(d.index.min()),
            'development_last_bar': str(d.index.max()),
            'admitted_session_days': int(len(sessions)),
            'admitted_session_days_by_year': {str(k): int(v) for k, v in by_year.items()},
            'first_admitted_day': str(sessions.index.min()),
            'last_admitted_day': str(sessions.index.max()),
        },
        'unconditional_session_mean_bps': {
            'asia': float(sessions['asia_return'].mean() * 10000.0),
            'europe': float(sessions['europe_return'].mean() * 10000.0),
            'us_liquid': float(sessions['us_liquid_return'].mean() * 10000.0),
        },
        'grid': {'hypotheses': int(len(hypotheses)), 'state_passes': int(sum(bool(x.get('state_pass')) for x in hypotheses))},
        'selected_state_relations_for_separate_freeze': [x['hypothesis_id'] for x in selected],
        'pnl_tested': False,
        'locked_internal_validation_opened': False,
        'retrospective_extension_opened': False,
        'leverage_tested': False,
        'claims': cfg['claims'],
        'hypotheses': hypotheses,
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(clean(payload), indent=2), encoding='utf-8')
    print(json.dumps(clean({
        'admitted_days': payload['data_integrity']['admitted_session_days'],
        'hypotheses': payload['grid']['hypotheses'],
        'state_passes': payload['grid']['state_passes'],
        'selected': payload['selected_state_relations_for_separate_freeze'],
        'pnl_tested': False,
        'locked_internal_validation_opened': False,
    }), indent=2))


if __name__ == '__main__':
    main()
