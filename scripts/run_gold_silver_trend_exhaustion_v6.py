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


def pf(values) -> float:
    x = np.asarray(values, float)
    pos = float(x[x > 0].sum())
    neg = float(-x[x < 0].sum())
    if neg <= 0:
        return 999.0 if pos > 0 else 0.0
    return pos / neg


def rho(a, b) -> float:
    a = pd.Series(a, dtype=float)
    b = pd.Series(b, dtype=float)
    m = a.notna() & b.notna() & np.isfinite(a) & np.isfinite(b)
    if int(m.sum()) < 4:
        return float('nan')
    return float(a[m].rank(method='average').corr(b[m].rank(method='average')))


def load_cash(path: Path, prefix: str, min_tick: int) -> pd.DataFrame:
    d = pd.read_csv(path)
    d.columns = [str(c).strip().lower() for c in d.columns]
    need = ['time', 'open', 'high', 'low', 'close', 'tick_volume']
    missing = [c for c in need if c not in d.columns]
    if missing:
        raise ValueError(f'{path}: missing {missing}')
    d['time'] = pd.to_datetime(d['time'], utc=True, errors='coerce').dt.floor('D')
    for c in need[1:]:
        d[c] = pd.to_numeric(d[c], errors='coerce')
    d = d.dropna(subset=need)
    d = d[(d[['open', 'high', 'low', 'close']] > 0).all(axis=1)]
    d = d[d['tick_volume'] >= min_tick]
    d = d[d['time'].dt.weekday <= 4]
    d = d.drop_duplicates('time', keep='last').set_index('time').sort_index()
    return d[['open', 'high', 'low', 'close', 'tick_volume']].add_prefix(prefix + '_')


def adaptive_states(d: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    m = cfg['pair_model']
    warm = int(m['initial_warmup_trading_days'])
    lam = float(m['forgetting_factor'])
    y = np.log(d['gold_close'].to_numpy(float))
    x = np.log(d['silver_close'].to_numpy(float))
    out = pd.DataFrame(index=d.index, columns=['alpha', 'beta', 'innovation', 'innovation_sd', 'z'], dtype=float)
    X0 = np.column_stack([np.ones(warm), x[:warm]])
    theta, *_ = np.linalg.lstsq(X0, y[:warm], rcond=None)
    resid = y[:warm] - X0 @ theta
    var = float(np.var(resid, ddof=0))
    gram = (X0.T @ X0) / float(warm)
    P = np.linalg.inv(gram + 1e-8 * np.eye(2))
    for i in range(warm, len(d)):
        xt = np.array([1.0, x[i]], float)
        pred = float(xt @ theta)
        innov = float(y[i] - pred)
        sd = float(math.sqrt(max(var, 1e-12)))
        out.iloc[i] = [float(theta[0]), float(theta[1]), innov, sd, innov / sd]
        Px = P @ xt
        den = float(lam + xt @ Px)
        K = Px / den
        theta = theta + K * innov
        P = (P - np.outer(K, xt) @ P) / lam
        P = 0.5 * (P + P.T)
        var = float(lam * var + (1.0 - lam) * innov * innov)
    return out


def admitted(s: pd.Series, cfg: dict) -> bool:
    m = cfg['pair_model']
    vals = [s.get('alpha'), s.get('beta'), s.get('innovation'), s.get('innovation_sd'), s.get('z')]
    return all(np.isfinite(float(v)) for v in vals) and float(s['beta']) > float(m['beta_gt']) and float(s['beta']) < float(m['beta_lt'])


def pair_close_return(d: pd.DataFrame, i0: int, i1: int, beta: float) -> float:
    gr = float(d['gold_close'].iloc[i1] / d['gold_close'].iloc[i0] - 1.0)
    sr = float(d['silver_close'].iloc[i1] / d['silver_close'].iloc[i0] - 1.0)
    b = abs(beta)
    wg = 1.0 / (1.0 + b)
    ws = b / (1.0 + b)
    return float(wg * gr - ws * sr)


def pair_open_components(d: pd.DataFrame, i0: int, i1: int, beta: float) -> tuple[float, float, float]:
    gr = float(d['gold_open'].iloc[i1] / d['gold_open'].iloc[i0] - 1.0)
    sr = float(d['silver_open'].iloc[i1] / d['silver_open'].iloc[i0] - 1.0)
    b = abs(beta)
    wg = 1.0 / (1.0 + b)
    ws = b / (1.0 + b)
    return float(wg * gr - ws * sr), gr, float(0.5 * gr - 0.5 * sr)


def prior_zscore(raw: pd.Series, window: int) -> pd.Series:
    prior = raw.shift(1)
    mu = prior.rolling(window, min_periods=window).mean()
    sd = prior.rolling(window, min_periods=window).std(ddof=0).replace(0, np.nan)
    return (raw - mu) / sd


def build_trend_exhaustion_score(d: pd.DataFrame, states: pd.DataFrame, cfg: dict) -> pd.Series:
    n = len(d)
    beta = states['beta']
    z = states['z']
    raw_trend = pd.Series(np.nan, index=d.index, dtype=float)
    for i in range(21, n):
        if np.isfinite(beta.iloc[i]):
            raw_trend.iloc[i] = pair_close_return(d, i - 21, i, float(beta.iloc[i]))
    trend_std = prior_zscore(raw_trend, int(cfg['feature']['standardization_window_trading_days']))
    return np.sign(z) * trend_std


def stable_seed(base: int, text: str) -> int:
    return int((base + int.from_bytes(hashlib.sha256(text.encode()).digest()[:4], 'big')) % (2**32 - 1))


def sign_flip_pvalue(rhos: list[float], epochs: int, seed: int) -> float:
    r = np.asarray(rhos, float)
    r = r[np.isfinite(r)]
    if len(r) == 0:
        return float('nan')
    obs = float(np.median(r))
    if obs <= 0:
        return 1.0
    rng = np.random.default_rng(seed)
    a = np.abs(r)
    count = 0
    done = 0
    while done < epochs:
        k = min(2000, epochs - done)
        signs = rng.choice(np.array([-1.0, 1.0]), size=(k, len(a)))
        count += int(np.sum(np.median(signs * a[None, :], axis=1) >= obs))
        done += k
    return float((count + 1) / (epochs + 1))


def fold_ra(frame: pd.DataFrame, col: str) -> float:
    vals = []
    for _, g in frame.groupby('fold'):
        x = g[col].to_numpy(float)
        if len(x) < 2:
            continue
        sd = float(np.std(x, ddof=1))
        if np.isfinite(sd) and sd > 0:
            vals.append(float(np.mean(x) / sd))
    return float(np.median(vals)) if vals else float('nan')


def side_stats(tr: pd.DataFrame, col: str, side: int) -> dict:
    g = tr[tr['pair_side'] == side]
    if g.empty:
        return {'trades': 0, 'mean_net_bps': np.nan, 'median_net_bps': np.nan, 'win_rate': np.nan}
    x = g[col].to_numpy(float)
    return {
        'trades': int(len(g)),
        'mean_net_bps': float(np.mean(x)),
        'median_net_bps': float(np.median(x)),
        'win_rate': float(np.mean(x > 0)),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', required=True)
    ap.add_argument('--gold', required=True)
    ap.add_argument('--silver', required=True)
    ap.add_argument('--output', required=True)
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding='utf-8'))
    min_tick = int(cfg['data_admission']['minimum_tick_volume_each_leg'])
    gold = load_cash(Path(args.gold), 'gold', min_tick)
    silver = load_cash(Path(args.silver), 'silver', min_tick)
    common = gold.join(silver, how='inner').dropna().sort_index()

    history_start = pd.Timestamp(cfg['pair_model']['history_initialization_start'], tz='UTC')
    end = pd.Timestamp(cfg['period']['end_exclusive'], tz='UTC')
    d = common.loc[(common.index >= history_start) & (common.index < end)].copy()
    states = adaptive_states(d, cfg)
    score = build_trend_exhaustion_score(d, states, cfg)

    start = pd.Timestamp(cfg['period']['start'], tz='UTC')
    h = int(cfg['state_test']['horizon_trading_bars'])
    cluster_days = int(cfg['state_test']['dependence_cluster_calendar_days'])
    folds = np.floor((d.index - start) / pd.Timedelta(days=cluster_days)).astype(int)
    event_z = float(cfg['pair_model']['event_abs_innovation_z_gte'])

    state_rows = []
    for i in range(len(d) - h):
        if d.index[i] < start or d.index[i] >= end:
            continue
        st = states.iloc[i]
        sc = score.iloc[i]
        if not admitted(st, cfg) or abs(float(st['z'])) < event_z or not np.isfinite(sc):
            continue
        j = i + h
        if d.index[j] >= end or folds[j] != folds[i]:
            continue
        target = float(-np.sign(float(st['z'])) * pair_close_return(d, i, j, float(st['beta'])))
        state_rows.append({'fold': int(folds[i]), 'score': float(sc), 'target': target, 'event_z': float(st['z'])})
    sf = pd.DataFrame(state_rows)
    fold_rhos = []
    if not sf.empty:
        for fid, g in sf.groupby('fold'):
            if len(g) < int(cfg['state_test']['minimum_events_per_fold']):
                continue
            rr = rho(g['score'], g['target'])
            if np.isfinite(rr):
                fold_rhos.append({'fold': int(fid), 'rho': float(rr), 'events': int(len(g))})
    rhos = [x['rho'] for x in fold_rhos]
    pval = sign_flip_pvalue(rhos, int(cfg['state_test']['sign_flip_epochs']), stable_seed(int(cfg['state_test']['sign_flip_seed']), cfg['feature']['name']))
    state_result = {
        'events': int(len(sf)),
        'positive_score_event_fraction': float((sf['score'] > 0).mean()) if not sf.empty else 0.0,
        'negative_score_event_fraction': float((sf['score'] < 0).mean()) if not sf.empty else 0.0,
        'scorable_folds': int(len(fold_rhos)),
        'fold_rhos': fold_rhos,
        'median_fold_spearman': float(np.median(rhos)) if rhos else np.nan,
        'positive_fold_fraction': float(np.mean(np.asarray(rhos) > 0)) if rhos else 0.0,
        'sign_flip_p': pval,
    }
    sgate = cfg['state_test']
    state_pass = bool(
        state_result['events'] >= int(sgate['minimum_total_events'])
        and state_result['scorable_folds'] >= int(sgate['minimum_scorable_folds'])
        and state_result['positive_score_event_fraction'] >= float(sgate['minimum_positive_score_event_fraction'])
        and state_result['negative_score_event_fraction'] >= float(sgate['minimum_negative_score_event_fraction'])
        and state_result['median_fold_spearman'] > float(sgate['minimum_median_fold_spearman'])
        and state_result['positive_fold_fraction'] >= float(sgate['minimum_positive_fold_fraction'])
        and state_result['sign_flip_p'] <= float(sgate['maximum_p_value'])
    )
    state_result['state_pass'] = state_pass

    hold = int(cfg['economic_translation']['hold_trading_bars'])
    rows = []
    i = 0
    while i + hold + 1 < len(d):
        if d.index[i] < start:
            i += 1
            continue
        if d.index[i] >= end:
            break
        st = states.iloc[i]
        sc = score.iloc[i]
        if not admitted(st, cfg) or abs(float(st['z'])) < event_z or not np.isfinite(sc) or float(sc) == 0:
            i += 1
            continue
        entry = i + 1
        exitp = entry + hold
        if d.index[exitp] >= end or folds[exitp] != folds[i]:
            i += 1
            continue
        mr_side = int(-np.sign(float(st['z'])))
        cont_side = -mr_side
        regime_side = mr_side if sc > 0 else cont_side
        original_v5_side = -regime_side
        pair, goldret, static = pair_open_components(d, entry, exitp, float(st['beta']))
        rows.append({
            'signal_time': str(d.index[i]),
            'entry_time': str(d.index[entry]),
            'exit_time': str(d.index[exitp]),
            'fold': int(folds[i]),
            'pair_side': int(regime_side),
            'regime_choice': 'reversion' if sc > 0 else 'continuation',
            'score': float(sc),
            'event_z': float(st['z']),
            'gross_bps': float(regime_side * pair * 10000.0),
            'original_v5_sign_gross_bps': float(original_v5_side * pair * 10000.0),
            'always_mr_gross_bps': float(mr_side * pair * 10000.0),
            'always_cont_gross_bps': float(cont_side * pair * 10000.0),
            'static_pair_gross_bps': float(regime_side * static * 10000.0),
            'unhedged_gold_gross_bps': float(regime_side * goldret * 10000.0),
        })
        i = exitp
    tr = pd.DataFrame(rows)
    econ = {'trades': int(len(tr))}
    if not tr.empty:
        costs = [float(x) for x in cfg['economic_translation']['round_trip_cost_bps_on_total_gross_notional']]
        primary = float(cfg['economic_translation']['primary_cost_bps'])
        high = float(cfg['economic_translation']['high_cost_bps'])
        for cost in costs:
            key = f'{cost:g}'
            col = f'net_{key}'
            tr[col] = tr['gross_bps'] - cost
            fn = tr.groupby('fold')[col].mean()
            fp = tr.groupby('fold')[col].apply(pf)
            econ[f'net_{key}_median_fold_bps'] = float(fn.median())
            econ[f'pf_{key}_median_fold'] = float(fp.median())
            econ[f'positive_fold_fraction_{key}'] = float((fn > 0).mean())
            econ[f'mean_net_{key}_bps'] = float(tr[col].mean())
        pkey = f'{primary:g}'
        pcol = f'net_{pkey}'
        for name in ['original_v5_sign', 'always_mr', 'always_cont', 'static_pair', 'unhedged_gold']:
            tr[f'{name}_net_primary'] = tr[f'{name}_gross_bps'] - primary
        econ['original_v5_sign_mean_net_primary_bps'] = float(tr['original_v5_sign_net_primary'].mean())
        econ['strategy_median_fold_risk_adjusted_primary'] = fold_ra(tr, pcol)
        econ['always_mr_median_fold_risk_adjusted_primary'] = fold_ra(tr, 'always_mr_net_primary')
        econ['always_cont_median_fold_risk_adjusted_primary'] = fold_ra(tr, 'always_cont_net_primary')
        econ['static_pair_median_fold_risk_adjusted_primary'] = fold_ra(tr, 'static_pair_net_primary')
        econ['unhedged_gold_median_fold_risk_adjusted_primary'] = fold_ra(tr, 'unhedged_gold_net_primary')
        econ['long_gold_short_silver'] = side_stats(tr, pcol, 1)
        econ['short_gold_long_silver'] = side_stats(tr, pcol, -1)
        econ['reversion_decisions'] = int((tr['regime_choice'] == 'reversion').sum())
        econ['continuation_decisions'] = int((tr['regime_choice'] == 'continuation').sum())
        eg = cfg['economic_gate']
        econ_pass = bool(
            state_pass
            and len(tr) >= int(eg['minimum_non_overlapping_trades'])
            and econ.get(f'net_{pkey}_median_fold_bps', -np.inf) > float(eg['minimum_primary_median_fold_net_bps'])
            and econ.get(f'pf_{pkey}_median_fold', 0.0) >= float(eg['minimum_primary_median_fold_pf'])
            and econ.get(f'positive_fold_fraction_{pkey}', 0.0) >= float(eg['minimum_primary_positive_fold_fraction'])
            and econ.get(f'net_{high:g}_median_fold_bps', -np.inf) >= float(eg['minimum_high_cost_median_fold_net_bps'])
            and econ.get(f'mean_net_{pkey}_bps', -np.inf) > float(eg['minimum_overall_mean_primary_net_bps'])
            and econ.get(f'mean_net_{pkey}_bps', -np.inf) > econ.get('original_v5_sign_mean_net_primary_bps', np.inf)
            and econ.get('strategy_median_fold_risk_adjusted_primary', -np.inf) > econ.get('always_mr_median_fold_risk_adjusted_primary', np.inf)
            and econ.get('strategy_median_fold_risk_adjusted_primary', -np.inf) > econ.get('always_cont_median_fold_risk_adjusted_primary', np.inf)
            and econ.get('long_gold_short_silver', {}).get('trades', 0) >= int(eg['minimum_long_gold_short_silver_trades'])
            and econ.get('short_gold_long_silver', {}).get('trades', 0) >= int(eg['minimum_short_gold_long_silver_trades'])
            and econ.get('long_gold_short_silver', {}).get('mean_net_bps', -np.inf) > 0
            and econ.get('short_gold_long_silver', {}).get('mean_net_bps', -np.inf) > 0
        )
        econ['economic_pass'] = econ_pass
        econ['trade_rows'] = rows
    else:
        econ['economic_pass'] = False

    payload = {
        'schema_version': 1,
        'protocol': cfg['protocol_name'],
        'evidence_class': cfg['evidence_class'],
        'period': cfg['period'],
        'data_integrity': {
            'common_rows_through_period_end': int(len(d)),
            'first_bar': str(d.index.min()),
            'last_bar': str(d.index.max()),
        },
        'state_result': state_result,
        'economic_result': econ,
        'protocol_pass': bool(state_pass and econ.get('economic_pass', False)),
        'future_shadow_authorized': False,
        'leverage_tested': False,
        'claims': cfg['claims'],
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(clean(payload), indent=2), encoding='utf-8')
    print(json.dumps(clean({
        'state_result': state_result,
        'economic_summary': {k: v for k, v in econ.items() if k != 'trade_rows'},
        'protocol_pass': payload['protocol_pass'],
        'future_shadow_authorized': payload['future_shadow_authorized'],
    }), indent=2))


if __name__ == '__main__':
    main()
