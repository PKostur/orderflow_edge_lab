"""Deferred tests of the 2026-10-16 evidence audit (reports/Deeper branch evidence audit.md, Sections 0.2 to 0.9).

Runs once on a GitHub-hosted runner (audit-deferred-v1.yml), which can reach MEXC, data.binance.vision, Hyperliquid
and the artifact store (Binance's fapi answers 451 to US runners, so Binance data comes from data.binance.vision).
Descriptive only: reads artifacts and public market data, writes one JSON result, never changes a watch.
Sections: C1, B1, C2, C3 (prices; funding deferred), C4, D4 + D5, S1_hyperliquid_common.  Each section records its
own error instead of stopping the run, the result file is rewritten after every section, and nothing is retried
beyond each fetcher's own retries.
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import importlib.util
import io
import json
import math
import os
import subprocess
import sys
import tempfile
import traceback
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from statistics import NormalDist
from typing import Any, Callable

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
BCFG = json.loads((ROOT / "config/multi_premia_blend_v1.json").read_text(encoding="utf-8"))
DEV_START, DEV_END = "2020-06-01", "2026-09-12"
C3_START = "2026-10-04"
REVISION_TOL = 1e-9
B1_MIN_DAYS = 10
D4_MAX_EMPTY_FUNDING_SHARE = 0.25
ALIAS = {"FILECOIN": "FIL", "TRUMPOFFICIAL": "TRUMP", "PUMPFUN": "PUMP"}
REPORT_ARTIFACT_BY_FILE = {"near_miss_forward_report.json": "near-miss-forward-v1",
                           "fade24_forward_report.json": "fade24-forward-v1",
                           "tradfi_perps_forward_report.json": "tradfi-perps-forward-v1"}
ARTIFACT_BY_WORKFLOW = {"multi-premia-blend-v1.yml": "multi-premia-blend-v1",
                        "crypto-trend-core-v1.yml": "crypto-trend-core-v1",
                        "crypto-trend-core-voltarget-v1.yml": "crypto-trend-core-voltarget-v1",
                        "trend-portfolio-forward-v1.yml": "trend-portfolio-forward-v1",
                        "cross-asset-trend-forward-v1.yml": "cross-asset-trend-forward-v1",
                        "cross-asset-trend-invvol-forward-v1.yml": "cross-asset-trend-invvol-forward-v1",
                        "news-sentiment-v1.yml": "news-sentiment-ledger-v1",
                        "canonical-v3-forward-companion-v1.yml": "canonical-v3-forward-companion-v1"}
C2_MODULES = [  # (artifact, report file, module argv)
    ("multi-premia-blend-v1", "report.json", ["orderflow_edge_lab.multi_premia_forward"]),
    ("multi-premia-blend-v1", "human_report.json", ["orderflow_edge_lab.multi_premia_human_forward"]),
    ("multi-premia-blend-v1", "zoo_mirror_report.json", ["orderflow_edge_lab.zoo_mirror_forward"]),
    ("crypto-trend-core-v1", "report.json",
     ["orderflow_edge_lab.cross_asset_trend_forward", "--config", "config/crypto_trend_core_v1.json"]),
    ("crypto-trend-core-voltarget-v1", "report.json",
     ["orderflow_edge_lab.core_voltarget_forward", "--config", "config/crypto_trend_core_voltarget_v1.json"]),
]


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _clean(o: Any) -> Any:
    """JSON-safe: NaN/inf -> None, numpy scalars -> Python."""
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return f if math.isfinite(f) else None
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def watches() -> list[tuple[str, str, str, str]]:
    """(display name, artifact name, report file, primary book) from dashboard_snapshot.WATCHES, read without importing."""
    tree = ast.parse((ROOT / "scripts/dashboard_snapshot.py").read_text(encoding="utf-8"))
    rows: list = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "WATCHES" for t in node.targets):
            rows = ast.literal_eval(node.value)
            break
    out = []
    for wf, report, name, _group, book, _h in rows:
        art = REPORT_ARTIFACT_BY_FILE.get(report) or ARTIFACT_BY_WORKFLOW.get(wf)
        if book and art:
            out.append((name, art, report, book))
    return out


# ---------------------------------------------------------------- artifacts
def fetch_artifacts(repo: str, token: str, names: set[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    arch = _load_script("archive_forward_artifacts")
    out, errors, seen = [], [], set()
    for a in arch.list_artifacts(repo, token):
        if a["name"] not in names or a.get("expired") or int(a["id"]) in seen:
            continue
        seen.add(int(a["id"]))
        try:
            with zipfile.ZipFile(io.BytesIO(arch._get(a["archive_download_url"], token))) as z:
                files = {}
                for info in z.infolist():
                    if info.filename.endswith(".json"):
                        try:
                            files[Path(info.filename).name] = json.loads(z.read(info))
                        except ValueError:
                            pass
        except Exception as exc:
            errors.append({"artifact": a["id"], "name": a["name"], "error": repr(exc)[:300]})
            continue
        out.append({"id": a["id"], "name": a["name"], "created_at": a["created_at"],
                    "head_sha": a["workflow_run"].get("head_sha"), "files": files})
    return sorted(out, key=lambda a: (a["created_at"], a["id"])), errors


def series_of(report: dict[str, Any] | None, book: str) -> pd.Series | None:
    if not report:
        return None
    d = (report.get("daily_returns") or {}).get(book)
    if not d:
        return None
    return pd.Series({pd.Timestamp(k): float(v) for k, v in d.items()}).sort_index()


def c1_revisions(arts, wl) -> dict[str, Any]:
    out = {}
    for name, art, report, book in wl:
        seen: dict[str, list[tuple[str, int, float]]] = {}
        n_art = 0
        for a in arts:
            if a["name"] != art:
                continue
            s = series_of(a["files"].get(report), book)
            if s is None:
                continue
            n_art += 1
            for t, v in s.items():
                seen.setdefault(t.isoformat(), []).append((a["created_at"], a["id"], v))
        revs = []
        for t, obs in sorted(seen.items()):
            vals = [v for _, _, v in obs]
            if max(vals) - min(vals) > REVISION_TOL:
                first, last = obs[0], obs[-1]
                revs.append({"stamp": t, "n_obs": len(obs), "min": min(vals), "max": max(vals),
                             "first": {"created_at": first[0], "artifact": first[1], "value": first[2]},
                             "last": {"created_at": last[0], "artifact": last[1], "value": last[2]}})
        out[name] = {"artifacts_with_series": n_art, "stamps": len(seen), "revised_stamps": len(revs), "revisions": revs[:60]}
    return out


def latest_series(arts, wl) -> dict[str, pd.Series]:
    out = {}
    for name, art, report, book in wl:
        for a in reversed(arts):
            if a["name"] == art and report in a["files"]:
                s = series_of(a["files"][report], book)
                if s is not None and len(s):
                    out[name] = s
                break
    return out


def b1_family(latest: dict[str, pd.Series]) -> dict[str, Any]:
    from orderflow_edge_lab.review_methods import bh_family, expected_max_normal_z
    from orderflow_edge_lab.trend_portfolio_forward import summarize

    p, per, included, excluded = {}, {}, {}, {}
    for name, s in latest.items():
        sm = summarize(s, nw_lags=5)
        t = sm["newey_west_t"]
        per[name] = {"days": sm["days"], "annualized_sharpe": sm["annualized_sharpe"], "newey_west_t": t,
                     "cumulative_return": sm["cumulative_return"]}
        if t is not None and math.isfinite(t):
            p[name] = 1.0 - NormalDist().cdf(t)
        gaps = s.index.to_series().diff().dropna()
        calendar_daily = bool(len(gaps) == 0 or (gaps == pd.Timedelta(days=1)).all())
        if len(s) < B1_MIN_DAYS:
            excluded[name] = f"fewer than {B1_MIN_DAYS} scored days"
        elif not calendar_daily:
            excluded[name] = "stamps are not calendar-daily"
        elif float(s.std(ddof=1)) == 0.0:
            excluded[name] = "constant series"
        else:
            included[name] = s
    frame = pd.DataFrame(included).dropna()
    res: dict[str, Any] = {"watches": per, "excluded_from_n_eff": excluded, "included": list(frame.columns),
                           "common_days": int(len(frame))}
    if len(frame) >= 5 and frame.shape[1] >= 2:
        c = frame.corr().values
        np.fill_diagonal(c, 1.0)
        c = np.nan_to_num(c, nan=0.0)
        lam = np.linalg.eigvalsh(c)
        n_eff = float(lam.sum() ** 2 / (lam ** 2).sum())
        res.update({"n_eff": n_eff, "eigenvalues": [float(x) for x in lam],
                    "expected_max_z_at_n_eff": expected_max_normal_z(max(1, round(n_eff))),
                    "correlation": pd.DataFrame(c, index=frame.columns, columns=frame.columns).round(3).to_dict()})
    else:
        res["n_eff"] = None
        res["note"] = "fewer than 5 common days or fewer than 2 included watches: N_eff not estimable"
    res["bh_q010"] = bh_family(p, q=0.10) if p else {}
    return res


def c2_determinism(arts) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for art, report, argv in C2_MODULES:
        key = f"{art}/{report}"
        latest = next((a for a in reversed(arts) if a["name"] == art and report in a["files"]), None)
        if latest is None:
            out[key] = {"error": "no artifact"}
            continue
        ref = latest["files"][report]
        as_of = ref.get("as_of_utc")
        try:
            with tempfile.TemporaryDirectory() as d:
                outp = Path(d) / "r.json"
                cmd = [sys.executable, "-m", *argv, "--output", str(outp), "--as-of", str(as_of)]
                proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=3600)
                if proc.returncode != 0:
                    out[key] = {"as_of": as_of, "error": proc.stderr[-2000:]}
                    continue
                new = json.loads(outp.read_text(encoding="utf-8"))
        except subprocess.TimeoutExpired:
            out[key] = {"as_of": as_of, "error": "timeout after 3600 s"}
            continue
        books, ok = {}, True
        for book in sorted(set(ref.get("daily_returns", {})) | set(new.get("daily_returns", {}))):
            a, b = ref.get("daily_returns", {}).get(book, {}), new.get("daily_returns", {}).get(book, {})
            same_keys = set(a) == set(b)
            gap = max((abs(a[k] - b[k]) for k in set(a) & set(b)), default=0.0)
            books[book] = {"same_stamps": same_keys, "n_ref": len(a), "n_new": len(b), "max_abs_gap": gap}
            ok = ok and same_keys and gap <= REVISION_TOL
        out[key] = {"as_of": as_of, "artifact": latest["id"], "artifact_head_sha": latest["head_sha"], "pass": ok,
                    "coins_with_data": {"ref": ref.get("coins_with_data"), "new": new.get("coins_with_data")},
                    "missing_symbols": {"ref": ref.get("missing_symbols"), "new": new.get("missing_symbols")},
                    "books": books}
    out["paper_account_report.json"] = {"not_testable": "paper_account has no --as-of option"}
    return out


# ---------------------------------------------------------------- market data
def binance_candidates(sym: str) -> list[str]:
    base = sym.replace("_USDT", "")
    base = ALIAS.get(base, base)
    return [f"{base}USDT", f"1000{base}USDT"]


def binance_archive(dataset: str, sym: str, start: str, end: str) -> tuple[str | None, pd.DataFrame]:
    """First candidate contract with data in data.binance.vision ('perp' 1h klines or 'funding')."""
    from orderflow_edge_lab.binance_futures_archive import load_dataset

    for cand in binance_candidates(sym):
        f = load_dataset(dataset, cand, start=start, end=end)
        if len(f):
            return cand, f
    return None, pd.DataFrame()


def _binance_daily_open(f: pd.DataFrame) -> pd.Series:
    """00:00 UTC open = open of the 1h bar ending 01:00 (archive frames are indexed by bar end)."""
    s = f["open"][f.index.hour == 1]
    s.index = s.index.floor("D")
    return s.astype(float)


def c3_reconcile(end: pd.Timestamp) -> dict[str, Any]:
    from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines
    from orderflow_edge_lab.xs_premia import daily_open_panel

    end_day = (end - pd.Timedelta(days=1)).strftime("%Y-%m-%d")

    def load(s):
        err = {}
        try:
            m = fetch_mexc_futures_klines(s, "8h", f"{C3_START}T00:00:00Z", end.isoformat())
        except Exception as exc:
            m, err["mexc"] = None, repr(exc)[:300]
        try:
            cand, b = binance_archive("perp", s, C3_START, end_day)
        except Exception as exc:
            cand, b, err["binance"] = None, pd.DataFrame(), repr(exc)[:300]
        return s, m, cand, b, err

    with ThreadPoolExecutor(4) as ex:
        got = list(ex.map(load, BCFG["symbols"]))
    mex = {s: m for s, m, c, b, _ in got if m is not None and len(m) and len(b)}
    bopen = pd.DataFrame({s: _binance_daily_open(b) for s, m, c, b, _ in got if s in mex})
    problems = {s: (e or {"binance": "no contract in archive"}) for s, m, c, b, e in got if s not in mex}
    om = daily_open_panel(mex)
    rm, rb = (om.shift(-1) / om - 1.0), (bopen.shift(-1) / bopen - 1.0)
    rm, rb = rm.align(rb, join="inner")
    gap = (rm - rb).abs()
    n = int(gap.notna().values.sum())
    exc_r = [{"date": d.isoformat(), "symbol": s, "mexc": float(rm.at[d, s]), "binance": float(rb.at[d, s]),
              "gap_bps": float(gap.at[d, s] * 1e4)} for d, s in gap[gap > 0.005].stack().index]
    return {"coins_compared": len(mex), "problems": problems, "window": [C3_START, end_day],
            "contracts": {s: c for s, m, c, b, _ in got if s in mex},
            "stamp_convention": "d = open(d) to open(d+1), one day earlier than the watches' stamps",
            "returns": {"coin_days": n, "exceptions_gt_50bps": len(exc_r),
                        "exception_rate": (len(exc_r) / n) if n else None,
                        "median_gap_bps": float(np.nanmedian(gap.values) * 1e4) if n else None,
                        "p95_gap_bps": float(np.nanpercentile(gap.values, 95) * 1e4) if n else None,
                        "exceptions": exc_r[:300]},
            "funding": {"status": "DEFERRED", "reason": "data.binance.vision publishes fundingRate monthly only; "
                                                         "the 2026-10 file is needed (addendum 0.9)"}}


def c4_beta(latest: dict[str, pd.Series], end: pd.Timestamp, reports: dict[str, dict]) -> dict[str, Any]:
    import statsmodels.api as sm

    from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines
    from orderflow_edge_lab.xs_premia import daily_open_panel

    btc = daily_open_panel({"BTC_USDT": fetch_mexc_futures_klines("BTC_USDT", "8h", "2026-09-15T00:00:00Z",
                                                                   end.isoformat())})["BTC_USDT"]
    rbtc = btc.pct_change()
    out = {}
    for name, s in latest.items():
        x = pd.concat([s.rename("w"), rbtc.rename("btc")], axis=1, join="inner").dropna()
        fields = sorted(k for k in (reports.get(name) or {}) if "funding" in k or "cost" in k or "fee" in k)
        if len(x) < 8:
            out[name] = {"n": len(x), "note": "fewer than 8 aligned days", "report_cost_funding_fields": fields}
            continue
        fit = sm.OLS(x["w"], sm.add_constant(x["btc"])).fit(cov_type="HAC", cov_kwds={"maxlags": 5})
        out[name] = {"n": int(len(x)), "beta": float(fit.params["btc"]), "beta_t": float(fit.tvalues["btc"]),
                     "alpha_daily": float(fit.params["const"]), "alpha_t": float(fit.tvalues["const"]),
                     "r2": float(fit.rsquared), "btc_cum_return": float((1 + x["btc"]).prod() - 1),
                     "watch_cum_return": float((1 + x["w"]).prod() - 1), "report_cost_funding_fields": fields}
    return out


def dev_data() -> tuple[dict, dict, dict[str, Any]]:
    """Development construction: MEXC 8h klines + Binance funding (data.binance.vision monthly files)."""
    from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines

    errors: dict[str, str] = {}

    def load(s):
        try:
            f = fetch_mexc_futures_klines(s, "8h", f"{DEV_START}T00:00:00Z", f"{DEV_END}T00:00:00Z")
        except Exception as exc:
            return s, None, None, f"mexc: {exc!r}"[:300]
        try:
            _, fr = binance_archive("funding", s, DEV_START, DEV_END)
            fu = fr["rate"].astype(float) if len(fr) else pd.Series(dtype=float)
            fu = fu[(fu.index >= pd.Timestamp(DEV_START, tz="UTC")) & (fu.index < pd.Timestamp(DEV_END, tz="UTC"))]
            fu = fu[~fu.index.duplicated(keep="first")]
        except Exception as exc:
            return s, f, pd.Series(dtype=float), f"binance funding: {exc!r}"[:300]
        return s, f, fu, None

    with ThreadPoolExecutor(4) as ex:
        got = list(ex.map(load, BCFG["symbols"]))
    for s, f, fu, e in got:
        if e:
            errors[s] = e
    frames = {s: f for s, f, _, _ in got if f is not None and len(f) > 400}
    fund = {s: (fu if fu is not None else pd.Series(dtype=float)) for s, f, fu, _ in got if s in frames}
    empty = sorted(s for s, fu in fund.items() if len(fu) == 0)
    meta = {"coins": len(frames), "missing_or_short": sorted(set(BCFG["symbols"]) - set(frames)), "errors": errors,
            "empty_funding": empty, "empty_funding_share": (len(empty) / len(frames)) if frames else None}
    return frames, fund, meta


def run_xs_open_only(opens, fund, score, *, rebalance_days, q, cost_bps, min_names=8):
    """run_xs with the pre-registered D4 variant mask (open of day d only); everything else identical."""
    from orderflow_edge_lab.xs_premia import quantile_weights

    ret = opens.shift(-1) / opens - 1.0
    w = pd.Series(0.0, index=opens.columns)
    rows, turnover = {}, {}
    for i, d in enumerate(opens.index[:-1]):
        if i % rebalance_days == 0:
            sc = score.loc[d].where(opens.loc[d].notna())
            new = quantile_weights(sc, q) if sc.notna().sum() >= min_names else pd.Series(0.0, index=opens.columns)
            turnover[d] = float((new - w).abs().sum())
            w = new
        r = ret.loc[d].fillna(0.0)
        f = fund.loc[d] if d in fund.index else 0.0
        cost = turnover.get(d, 0.0) * cost_bps / 2.0 / 10_000.0
        rows[d] = float((w * r).sum() - (w * f).sum() - cost)
        w = w * (1.0 + r)
    return {"returns": pd.Series(rows).sort_index(), "turnover": pd.Series(turnover)}


def _stats(x: pd.Series) -> dict[str, Any]:
    from orderflow_edge_lab.trend_portfolio_forward import summarize

    s = summarize(x.dropna(), nw_lags=5)
    return {"sharpe": s["annualized_sharpe"], "t": s["newey_west_t"], "mean_daily": float(x.mean()), "days": s["days"]}


def d4_d5(frames, fund) -> dict[str, Any]:
    from orderflow_edge_lab.multi_premia_forward import blend, leg_returns
    from orderflow_edge_lab.xs_premia import carry_score, daily_funding_panel, daily_open_panel, momentum_score, run_xs
    from orderflow_edge_lab.xs_premia_pit import daily_last_close_panel, run_xs_pit

    c = BCFG["legs"]
    cost = float(BCFG["economics"]["round_trip_cost_bps"])
    base = leg_returns(BCFG, frames, fund)
    opens = daily_open_panel(frames)
    fp = daily_funding_panel(fund, opens.index)
    last_close = daily_last_close_panel(frames)
    m, k = c["S2_xs_momentum"], c["S3_xs_carry"]
    specs = {"S2": (momentum_score(opens, int(m["lookback_days"])), int(m["rebalance_days"]), float(m["quantile"])),
             "S3": (carry_score(fp, int(k["lookback_days"])), int(k["rebalance_days"]), float(k["quantile"]))}
    nxt = opens.shift(-1)
    variants: dict[str, Callable] = {
        "original": lambda sc, rb, q: run_xs(opens, fp, sc, rebalance_days=rb, q=q, cost_bps=cost),
        "open_only": lambda sc, rb, q: run_xs_open_only(opens, fp, sc, rebalance_days=rb, q=q, cost_bps=cost),
        "pit_successor": lambda sc, rb, q: run_xs_pit(opens, last_close, fp, sc, rebalance_days=rb, q=q, cost_bps=cost),
    }
    res: dict[str, Any] = {"coins": len(frames), "window": [DEV_START, DEV_END],
                           "construction": "MEXC 8h prices + Binance funding (data.binance.vision monthly files)"}
    legs_by = {}
    for vname, fn in variants.items():
        legs = {"S1": base["S1"]}
        info: dict[str, Any] = {}
        for leg, (sc, rb, q) in specs.items():
            o = fn(sc, rb, q)
            r = o["returns"].copy()
            r.index = r.index + pd.Timedelta(days=1)
            legs[leg] = r
            info[leg] = {"mean_turnover_per_rebalance": float(o["turnover"].mean())}
            if "settlements" in o:
                info[leg]["settlements"] = len(o["settlements"])
                info[leg]["settlements_without_price"] = sum(1 for x in o["settlements"] if x["price"] != "last_close")
        lg = pd.concat([pd.Series(v).rename(n) for n, v in legs.items()], axis=1).dropna()
        lg = lg[(lg != 0).all(axis=1).cumsum() > 0]
        lg["S4"] = blend(lg[["S1", "S2", "S3"]], vol_window=int(BCFG["blend"]["vol_window_days"]),
                         min_obs=int(BCFG["blend"]["min_obs"]))
        legs_by[vname] = lg
        res[vname] = {leg: {**_stats(lg[leg]), **info.get(leg, {})} for leg in ("S1", "S2", "S3", "S4")}
    drops: dict[str, Any] = {}
    for leg, (sc, rb, q) in specs.items():
        spec_n, scored_n = [], []
        for i, d in enumerate(opens.index[:-1]):
            if i % rb == 0:
                ending = opens.loc[d].notna() & nxt.loc[d].isna()
                spec_n.append(int(ending.sum()))
                scored_n.append(int((ending & sc.loc[d].notna()).sum()))
        drops[leg] = {"rebalances": len(spec_n),
                      "as_specified_open_d_none_d1": {"mean": float(np.mean(spec_n)), "total": int(np.sum(spec_n))},
                      "with_score": {"mean": float(np.mean(scored_n)), "total": int(np.sum(scored_n))}}
    res["dropped_by_mask_per_rebalance"] = drops
    chk = (legs_by["original"]["S2"] - base["S2"].reindex(legs_by["original"].index)).abs().max()
    res["sanity_original_S2_matches_leg_returns_max_abs"] = float(chk)
    for v in ("open_only", "pit_successor"):
        res[f"diff_{v}_minus_original"] = {
            leg: {"sharpe": (res[v][leg]["sharpe"] or 0.0) - (res["original"][leg]["sharpe"] or 0.0),
                  "mean_daily": res[v][leg]["mean_daily"] - res["original"][leg]["mean_daily"]}
            for leg in ("S2", "S3", "S4")}
    return res


def s1_hyperliquid(frames, fund) -> dict[str, Any]:
    from orderflow_edge_lab.multi_premia_forward import leg_returns

    hv = _load_script("hyperliquid_venue_check_2026_10_09")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        data = hv.fetch_all(BCFG["symbols"])
    fetch_errors = [line for line in buf.getvalue().splitlines() if line.startswith("fail")]
    coins = sorted(s for s in data if s in frames)

    def s1(fr, fu):
        lg = leg_returns(BCFG, fr, fu)
        lg = lg[(lg != 0).all(axis=1).cumsum() > 0]
        return lg["S1"]

    v = s1({s: data[s][1] for s in coins}, {s: data[s][2] for s in coins})
    r = s1({s: frames[s] for s in coins}, {s: fund[s] for s in coins})
    common = v.index.intersection(r.index)
    return {"coins": len(coins), "fetch_errors": fetch_errors, "window": [hv.START, hv.END],
            "common_days": int(len(common)),
            "first": str(common.min()) if len(common) else None, "last": str(common.max()) if len(common) else None,
            "hyperliquid_S1": _stats(v.loc[common]), "reference_S1": _stats(r.loc[common]),
            "daily_correlation": float(v.loc[common].corr(r.loc[common])) if len(common) > 2 else None}


class Runner:
    def __init__(self, output: Path, results: dict[str, Any]):
        self.output, self.results = output, results
        output.parent.mkdir(parents=True, exist_ok=True)
        self.write()

    def write(self) -> None:
        self.output.write_text(json.dumps(_clean(self.results), indent=1, sort_keys=True, default=str) + "\n",
                               encoding="utf-8")

    def fetch(self, key: str, fn: Callable[[], Any]) -> Any:
        """Run a data-loading step; store only its error (the caller stores metadata)."""
        try:
            return fn()
        except Exception:
            self.results[key] = {"error": traceback.format_exc()[-3000:]}
            self.write()
            print(f"[audit] {key}: error", flush=True)
            return None

    def section(self, key: str, fn: Callable[[], Any]) -> Any:
        try:
            self.results[key] = fn()
        except Exception:
            self.results[key] = {"error": traceback.format_exc()[-3000:]}
        self.write()
        bad = isinstance(self.results[key], dict) and "error" in self.results[key]
        print(f"[audit] {key}: {'error' if bad else 'done'}", flush=True)
        return self.results[key]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    a = p.parse_args(argv)
    output = a.output.resolve()
    os.chdir(ROOT)
    os.environ.setdefault("TEMP", tempfile.gettempdir())  # the reused venue scripts read TEMP at import
    token = os.environ["GH_TOKEN"]
    end = pd.Timestamp.now(tz="UTC").floor("h")
    wl = watches()
    run = Runner(output, {"audit": "deeper-branch-evidence-audit-2026-10-16", "run_utc": end.isoformat(),
                          "git_head": os.environ.get("GITHUB_SHA"), "descriptive_only": True,
                          "watch_list": [list(w) for w in wl]})
    fetched = run.fetch("artifacts_meta", lambda: fetch_artifacts(a.repo, token, {w[1] for w in wl}))
    arts: list[dict[str, Any]] = []
    if fetched is not None:
        arts, errors = fetched
        run.results["artifacts_meta"] = {"count": len(arts), "download_errors": errors,
                                         "first": arts[0]["created_at"] if arts else None,
                                         "last": arts[-1]["created_at"] if arts else None}
        run.write()
    latest = latest_series(arts, wl)
    reports = {}
    for name, art, report, _b in wl:
        for x in reversed(arts):
            if x["name"] == art and report in x["files"]:
                reports[name] = x["files"][report]
                break
    run.section("C1_revisions", lambda: c1_revisions(arts, wl))
    run.section("B1_family", lambda: b1_family(latest))
    run.section("C2_determinism", lambda: c2_determinism(arts))
    run.section("C3_reconciliation", lambda: c3_reconcile(end))
    run.section("C4_btc_beta", lambda: c4_beta(latest, end, reports))
    got = run.fetch("dev_data_meta", dev_data)
    if got is not None:
        frames, fund, meta = got
        run.results["dev_data_meta"] = meta
        run.write()
        share = meta["empty_funding_share"]
        if share is None or share > D4_MAX_EMPTY_FUNDING_SHARE:
            run.results["D4_D5_mask_size"] = {"aborted": f"empty Binance funding share {share} > {D4_MAX_EMPTY_FUNDING_SHARE}"}
            run.write()
        else:
            run.section("D4_D5_mask_size", lambda: d4_d5(frames, fund))
        run.section("S1_hyperliquid_common", lambda: s1_hyperliquid(frames, fund))
    print(json.dumps({k: ("error" if isinstance(v, dict) and "error" in v else "ok") for k, v in run.results.items()
                      if isinstance(v, dict)}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
