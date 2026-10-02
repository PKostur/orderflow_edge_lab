"""Strategy families for strategy-zoo-v2 (config/strategy_zoo_v2.json).

Daily books follow strategy_zoo conventions (keyed by the day held, open(d) -> open(d+1)). The two 8h books
return (net, gross) series already summed per UTC day.
"""

from __future__ import annotations

from typing import Mapping

import numpy as np
import pandas as pd

from orderflow_edge_lab.strategy_zoo import daily_returns, run_targets
from orderflow_edge_lab.xs_premia import daily_open_panel, momentum_score, quantile_weights, run_xs


def pairs_targets(opens: pd.DataFrame, *, formation: int = 90, zwin: int = 20, entry: float = 2.0, exit_: float = 0.5,
                  min_corr: float = 0.7, reform_days: int = 7) -> pd.DataFrame:
    logp = np.log(opens)
    r = logp.diff()
    cols = list(opens.columns)
    out = pd.DataFrame(0.0, index=opens.index, columns=cols)
    pairs: list[tuple[str, str]] = []
    state: dict[tuple[str, str], int] = {}
    max_pairs = 1
    for i, d in enumerate(opens.index):
        if i % reform_days == 0 and i >= formation:
            window = r.iloc[i - formation + 1:i + 1]
            live = [c for c in cols if window[c].notna().sum() == formation and pd.notna(opens.iloc[i][c])]
            max_pairs = max(1, len(live) // 4)
            new: list[tuple[str, str]] = []
            if len(live) >= 2:
                cm = window[live].corr().to_numpy()
                np.fill_diagonal(cm, -np.inf)
                used: set[int] = set()
                order = np.dstack(np.unravel_index(np.argsort(-cm, axis=None), cm.shape))[0]
                for a, b in order:
                    if len(new) >= max_pairs or cm[a, b] < min_corr:
                        break
                    if a < b and a not in used and b not in used:
                        new.append((live[a], live[b]))
                        used.update((a, b))
            state = {p: s for p, s in state.items() if p in new}
            pairs = new
        if not pairs:
            continue
        for p in pairs:
            a, b = p
            spread = (logp[a] - logp[b]).iloc[max(0, i - zwin + 1):i + 1]
            if spread.notna().sum() < zwin:
                continue
            sd = spread.std()
            if not sd > 0:
                continue
            z = (spread.iloc[-1] - spread.mean()) / sd
            s = state.get(p, 0)
            if s == 0 and z > entry:
                s = -1  # a rich vs b: short a, long b
            elif s == 0 and z < -entry:
                s = 1
            elif s != 0 and abs(z) < exit_:
                s = 0
            state[p] = s
            if s:
                g = 0.5 / max_pairs
                out.at[d, a] += s * g
                out.at[d, b] -= s * g
    return out


def eight_hour_panel(frames: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    return pd.DataFrame({s: f["open"].astype(float) for s, f in frames.items()}).sort_index()


def _run_8h(targets: pd.DataFrame, opens8: pd.DataFrame, *, cost_bps: float) -> tuple[pd.Series, pd.Series]:
    fwd = opens8.shift(-1) / opens8 - 1.0
    w = pd.Series(0.0, index=opens8.columns)
    net, gross = {}, {}
    for t in opens8.index[:-1]:
        new = targets.loc[t].where(fwd.loc[t].notna(), 0.0) if t in targets.index else pd.Series(0.0, index=opens8.columns)
        turn = float((new - w).abs().sum())
        r = fwd.loc[t].fillna(0.0)
        g = float((new * r).sum())
        gross[t], net[t] = g, g - turn * cost_bps / 2 / 1e4
        w = new * (1.0 + r)
    day = lambda s: pd.Series(s, dtype=float).groupby(lambda t: t.floor("D")).sum()  # noqa: E731
    return day(net), day(gross)


def us_session(frames: Mapping[str, pd.DataFrame], *, cost_bps: float) -> tuple[pd.Series, pd.Series]:
    o8 = eight_hour_panel(frames)
    ok = (o8.notna() & o8.shift(-1).notna()).astype(float)
    w = ok.div(ok.sum(axis=1).clip(lower=1), axis=0)
    w = w.mul(pd.Series(o8.index.hour == 16, index=o8.index).astype(float), axis=0)
    return _run_8h(w, o8, cost_bps=cost_bps)


def eight_hour_reversal(frames: Mapping[str, pd.DataFrame], *, cost_bps: float, min_names: int = 8) -> tuple[pd.Series, pd.Series]:
    o8 = eight_hour_panel(frames)
    prev = o8 / o8.shift(1) - 1.0
    fwd_ok = o8.shift(-1).notna()
    rows = {}
    for t in o8.index:
        sc = (-prev.loc[t]).where(fwd_ok.loc[t])
        rows[t] = quantile_weights(sc, 0.25) if sc.notna().sum() >= min_names else pd.Series(0.0, index=o8.columns)
    return _run_8h(pd.DataFrame(rows).T.reindex(columns=o8.columns).fillna(0.0), o8, cost_bps=cost_bps)


def highvol_breakout_targets(opens: pd.DataFrame, *, n_entry: int = 20, n_exit: int = 10, vol_win: int = 20,
                             vol_hist: int = 180, size_win: int = 60, target_vol: float = 0.15) -> pd.DataFrame:
    r = daily_returns(opens)
    vol = r.rolling(vol_win, min_periods=vol_win).std()
    vol_med = vol.rolling(vol_hist, min_periods=60).median().shift(1)
    hi_e, lo_e = opens.shift(1).rolling(n_entry, min_periods=n_entry).max(), opens.shift(1).rolling(n_entry, min_periods=n_entry).min()
    hi_x, lo_x = opens.shift(1).rolling(n_exit, min_periods=n_exit).max(), opens.shift(1).rolling(n_exit, min_periods=n_exit).min()
    size = (target_vol / (r.rolling(size_win, min_periods=size_win).std() * np.sqrt(365))).clip(upper=1.0)
    out = pd.DataFrame(0.0, index=opens.index, columns=opens.columns)
    for c in opens.columns:
        s, sz = 0, 0.0
        o, hv = opens[c].to_numpy(), (vol[c] > vol_med[c]).to_numpy()
        he, le, hx, lx, zz = hi_e[c].to_numpy(), lo_e[c].to_numpy(), hi_x[c].to_numpy(), lo_x[c].to_numpy(), size[c].to_numpy()
        col = np.zeros(len(o))
        for i in range(len(o)):
            if not np.isfinite(o[i]):
                s = 0
                continue
            if s == 1 and np.isfinite(lx[i]) and o[i] < lx[i]:
                s = 0
            elif s == -1 and np.isfinite(hx[i]) and o[i] > hx[i]:
                s = 0
            if s == 0 and hv[i] and np.isfinite(zz[i]):
                if np.isfinite(he[i]) and o[i] > he[i]:
                    s, sz = 1, zz[i]
                elif np.isfinite(le[i]) and o[i] < le[i]:
                    s, sz = -1, zz[i]
            col[i] = s * sz
        out[c] = col
    n = opens.notna().sum(axis=1).clip(lower=1)
    return out.div(n, axis=0)


def vol_managed_momentum(opens: pd.DataFrame, fund: pd.DataFrame, *, cost_bps: float, target_vol: float = 0.20,
                         window: int = 30) -> pd.Series:
    base = run_xs(opens, fund, momentum_score(opens, 30), rebalance_days=7, q=0.25, cost_bps=cost_bps)["returns"]
    realized = base.rolling(window, min_periods=window).std().shift(1) * np.sqrt(365)
    scale = (target_vol / realized).clip(upper=1.0).fillna(0.0)
    return base * scale  # approximation: turnover cost scales with the position


def zoo_v2_books(frames: Mapping[str, pd.DataFrame], fund_panel: pd.DataFrame, *, cost_bps: float = 20.0) -> tuple[pd.DataFrame, dict]:
    opens = daily_open_panel(frames)
    fund = fund_panel.reindex(opens.index).fillna(0.0)
    us_net, us_gross = us_session(frames, cost_bps=cost_bps)
    rv_net, rv_gross = eight_hour_reversal(frames, cost_bps=cost_bps)
    books = pd.DataFrame({
        "Y1_pairs": run_targets(pairs_targets(opens), opens, fund, cost_bps=cost_bps),
        "Y2_us_session": us_net,
        "Y3_8h_reversal": rv_net,
        "Y4_highvol_breakout": run_targets(highvol_breakout_targets(opens), opens, fund, cost_bps=cost_bps),
        "Y5_volmanaged_xs_momentum": vol_managed_momentum(opens, fund, cost_bps=cost_bps),
    })
    gross = {"Y2_us_session": us_gross, "Y3_8h_reversal": rv_gross}
    return books, gross
