from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from bs4 import BeautifulSoup


def clean(v):
    if isinstance(v, (float, np.floating)):
        x = float(v)
        return x if math.isfinite(x) else None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, dict):
        return {str(k): clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [clean(x) for x in v]
    return v


def pf(values) -> float:
    x = np.asarray(values, dtype=float)
    pos = float(x[x > 0].sum())
    neg = float(-x[x < 0].sum())
    if neg <= 0:
        return 999.0 if pos > 0 else 0.0
    return pos / neg


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


def sign_flip_pvalue(values: list[float], epochs: int, seed: int) -> float:
    x = np.asarray(values, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) == 0:
        return float("nan")
    observed = float(np.median(x))
    if observed <= 0:
        return 1.0
    rng = np.random.default_rng(seed)
    abs_x = np.abs(x)
    count = 0
    done = 0
    while done < epochs:
        n = min(2000, epochs - done)
        signs = rng.choice(np.array([-1.0, 1.0]), size=(n, len(abs_x)))
        null = np.median(signs * abs_x[None, :], axis=1)
        count += int(np.sum(null >= observed))
        done += n
    return float((count + 1) / (epochs + 1))


def load_m15(path: Path, cfg: dict) -> pd.DataFrame:
    d = pd.read_csv(path)
    d.columns = [str(c).strip().lower() for c in d.columns]
    req = ["time", "open", "high", "low", "close", "tick_volume"]
    missing = [c for c in req if c not in d.columns]
    if missing:
        raise ValueError(f"missing columns {missing}")
    d["time"] = pd.to_datetime(d["time"], utc=True, errors="coerce")
    for c in req[1:]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.dropna(subset=req)
    d = d[(d[["open", "high", "low", "close"]] > 0).all(axis=1)]
    d = d[d["tick_volume"] >= int(cfg["data_admission"]["minimum_tick_volume"])]
    d = d.drop_duplicates("time", keep="last").set_index("time").sort_index()
    return d[["open", "high", "low", "close", "tick_volume"]]


def parse_bls_dates(html: str, prefix: str) -> list[pd.Timestamp]:
    dates = set()
    pat = re.compile(rf"{re.escape(prefix)}_(\d{{8}})\.(?:htm|pdf)", re.I)
    for m in pat.finditer(html):
        try:
            dt = datetime.strptime(m.group(1), "%m%d%Y").date()
            dates.add(dt)
        except ValueError:
            pass
    return [pd.Timestamp(x) for x in sorted(dates)]


def month_number(text: str) -> int:
    key = text.strip().lower()[:3]
    mp = {"jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,"jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12}
    if key not in mp:
        raise ValueError(text)
    return mp[key]


def parse_fomc_regular_dates(html: str, year: int) -> list[pd.Timestamp]:
    soup = BeautifulSoup(html, "html.parser")
    dates = set()
    pattern = re.compile(
        r"([A-Za-z]+)(?:/([A-Za-z]+))?\s+(\d{1,2})(?:-(\d{1,2}))?\s+Meeting\s*-\s*(\d{4})",
        re.I,
    )
    for tag in soup.find_all(["h3", "h4", "h5", "h6"]):
        txt = " ".join(tag.get_text(" ", strip=True).split())
        low = txt.lower()
        if "unscheduled" in low or "cancelled" in low:
            continue
        m = pattern.search(txt)
        if not m:
            continue
        y = int(m.group(5))
        if y != year:
            continue
        m1 = month_number(m.group(1))
        m2 = month_number(m.group(2)) if m.group(2) else m1
        d1 = int(m.group(3))
        d2 = int(m.group(4)) if m.group(4) else d1
        decision_month = m2 if m.group(2) else m1
        try:
            dates.add(datetime(y, decision_month, d2).date())
        except ValueError:
            continue
    return [pd.Timestamp(x) for x in sorted(dates)]


def local_release_to_utc(date_ts: pd.Timestamp, hhmm: str, tz_name: str) -> pd.Timestamp:
    hh, mm = [int(x) for x in hhmm.split(":")]
    local = datetime.combine(date_ts.date(), time(hh, mm), tzinfo=ZoneInfo(tz_name))
    return pd.Timestamp(local.astimezone(ZoneInfo("UTC")))


def build_events(cfg: dict, cpi_html: str, empsit_html: str, fed_pages: dict[int, str]) -> pd.DataFrame:
    rows = []
    sources = cfg["event_sources"]
    for dt in parse_bls_dates(cpi_html, "cpi"):
        rows.append({"event_type": "cpi", "event_time": local_release_to_utc(dt, sources["cpi"]["release_time_local"], sources["cpi"]["timezone"])})
    for dt in parse_bls_dates(empsit_html, "empsit"):
        rows.append({"event_type": "employment_situation", "event_time": local_release_to_utc(dt, sources["employment_situation"]["release_time_local"], sources["employment_situation"]["timezone"])})
    for year, html in fed_pages.items():
        for dt in parse_fomc_regular_dates(html, year):
            rows.append({"event_type": "fomc", "event_time": local_release_to_utc(dt, sources["fomc"]["release_time_local"], sources["fomc"]["timezone"])})
    out = pd.DataFrame(rows).drop_duplicates(["event_type", "event_time"]).sort_values("event_time").reset_index(drop=True)
    return out


def exact_bar_return(d: pd.DataFrame, release: pd.Timestamp, hold_minutes: int, side: int) -> dict | None:
    t0 = release
    t15 = release + pd.Timedelta(minutes=15)
    entry_t = release + pd.Timedelta(minutes=30)
    exit_t = entry_t + pd.Timedelta(minutes=hold_minutes)
    if any(t not in d.index for t in [t0, t15, entry_t, exit_t]):
        return None
    event_open = float(d.at[t0, "open"])
    reaction_close = float(d.at[t15, "close"])
    entry = float(d.at[entry_t, "open"])
    exit_px = float(d.at[exit_t, "open"])
    reaction = reaction_close / event_open - 1.0
    future = exit_px / entry - 1.0
    return {
        "reaction": reaction,
        "future": future,
        "gross_bps": float(side * future * 10000.0),
        "entry_time": entry_t,
        "exit_time": exit_t,
    }


def placebo_return(d: pd.DataFrame, release: pd.Timestamp, hold_minutes: int, side: int) -> float | None:
    entry_t = release + pd.Timedelta(minutes=30)
    exit_t = entry_t + pd.Timedelta(minutes=hold_minutes)
    if entry_t not in d.index or exit_t not in d.index:
        return None
    return float(side * (float(d.at[exit_t, "open"]) / float(d.at[entry_t, "open"]) - 1.0) * 10000.0)


def evaluate_cell(d: pd.DataFrame, events: pd.DataFrame, event_type: str, mode: str, hold: int, start_ts: pd.Timestamp, cfg: dict) -> dict:
    cluster_days = int(cfg["state_first"]["dependence_cluster_calendar_days"])
    family_times = set(events.loc[events["event_type"] == event_type, "event_time"].tolist())
    rows = []
    for _, er in events[events["event_type"] == event_type].sort_values("event_time").iterrows():
        release = pd.Timestamp(er["event_time"])
        if release not in d.index or release + pd.Timedelta(minutes=15) not in d.index:
            continue
        reaction = float(d.at[release + pd.Timedelta(minutes=15), "close"] / d.at[release, "open"] - 1.0)
        if reaction == 0 or not np.isfinite(reaction):
            continue
        side = int(np.sign(reaction)) if mode == "continuation" else int(-np.sign(reaction))
        main = exact_bar_return(d, release, hold, side)
        if main is None:
            continue
        placebo = []
        for delta_days in (-7, 7):
            pt = release + pd.Timedelta(days=delta_days)
            if pt in family_times:
                continue
            pr = placebo_return(d, pt, hold, side)
            if pr is not None:
                placebo.append(pr)
        placebo_mean = float(np.mean(placebo)) if placebo else np.nan
        fold = int(math.floor((release - start_ts) / pd.Timedelta(days=cluster_days)))
        rows.append({
            "event_type": event_type,
            "mode": mode,
            "hold_minutes": int(hold),
            "release_time": str(release),
            "fold": fold,
            "side": side,
            "initial_reaction_bps": float(main["reaction"] * 10000.0),
            "gross_bps": float(main["gross_bps"]),
            "placebo_mean_gross_bps": placebo_mean,
            "state_excess_bps": float(main["gross_bps"] - placebo_mean) if np.isfinite(placebo_mean) else np.nan,
            "placebo_count": int(len(placebo)),
            "entry_time": str(main["entry_time"]),
            "exit_time": str(main["exit_time"]),
        })
    tr = pd.DataFrame(rows)
    cid = f"{event_type}__{mode}__hold{hold}m"
    out = {
        "candidate_id": cid,
        "event_type": event_type,
        "mode": mode,
        "hold_minutes": int(hold),
        "events": int(len(tr)),
    }
    if tr.empty:
        return out
    min_events = int(cfg["state_first"]["minimum_events_per_scorable_fold"])
    fold_rows = []
    state_tr = tr[np.isfinite(tr["state_excess_bps"])].copy()
    for fid, g in state_tr.groupby("fold"):
        if len(g) < min_events:
            continue
        fold_rows.append({
            "fold": int(fid),
            "events": int(len(g)),
            "mean_state_excess_bps": float(g["state_excess_bps"].mean()),
            "mean_event_gross_bps": float(g["gross_bps"].mean()),
            "mean_placebo_gross_bps": float(g["placebo_mean_gross_bps"].mean()),
        })
    excess_means = [x["mean_state_excess_bps"] for x in fold_rows]
    out["state_folds"] = int(len(fold_rows))
    out["state_fold_metrics"] = fold_rows
    out["state_median_fold_excess_bps"] = float(np.median(excess_means)) if excess_means else np.nan
    out["state_positive_fold_fraction"] = float(np.mean(np.asarray(excess_means) > 0)) if excess_means else 0.0
    out["state_sign_flip_p"] = sign_flip_pvalue(
        excess_means,
        int(cfg["state_first"]["fold_mean_sign_flip_epochs"]),
        int(cfg["state_first"]["fold_mean_sign_flip_seed"]) + abs(hash(cid)) % 100000,
    )
    costs = [float(x) for x in cfg["execution"]["round_trip_cost_bps"]]
    for cost in costs:
        key = f"{cost:g}"
        col = f"net_{key}"
        tr[col] = tr["gross_bps"] - cost
        fold_net = tr.groupby("fold")[col].mean()
        fold_pf = tr.groupby("fold")[col].apply(pf)
        out[f"net_{key}_median_fold_bps"] = float(fold_net.median())
        out[f"pf_{key}_median_fold"] = float(fold_pf.median())
        out[f"positive_fold_fraction_{key}"] = float((fold_net > 0).mean())
        out[f"mean_net_{key}_bps"] = float(tr[col].mean())
    primary = float(cfg["execution"]["primary_cost_bps"])
    pkey = f"{primary:g}"
    pcol = f"net_{pkey}"
    out["reversed_mean_net_primary_bps"] = float((-tr["gross_bps"] - primary).mean())
    out["event_mean_gross_bps"] = float(tr["gross_bps"].mean())
    out["placebo_mean_gross_bps"] = float(tr["placebo_mean_gross_bps"].dropna().mean()) if tr["placebo_mean_gross_bps"].notna().any() else np.nan
    longs = tr[tr["side"] > 0]
    shorts = tr[tr["side"] < 0]
    out["long"] = {
        "trades": int(len(longs)),
        "mean_net_bps": float(longs[pcol].mean()) if len(longs) else np.nan,
    }
    out["short"] = {
        "trades": int(len(shorts)),
        "mean_net_bps": float(shorts[pcol].mean()) if len(shorts) else np.nan,
    }
    out["trade_rows"] = tr.to_dict(orient="records")
    return out


def apply_gates(cells: list[dict], cfg: dict) -> None:
    qvals = bh_qvalues([c.get("state_sign_flip_p", np.nan) for c in cells])
    s = cfg["state_first"]
    e = cfg["economic_gate"]
    pkey = f"{float(cfg['execution']['primary_cost_bps']):g}"
    hkey = f"{float(cfg['execution']['high_cost_bps']):g}"
    for c, q in zip(cells, qvals):
        c["state_bh_q"] = q
        c["state_pass"] = bool(
            c.get("state_folds", 0) >= int(s["minimum_scorable_folds"])
            and c.get("state_median_fold_excess_bps", -np.inf) > float(s["minimum_median_fold_excess_bps"])
            and c.get("state_positive_fold_fraction", 0.0) >= float(s["minimum_positive_fold_fraction"])
            and c.get("state_bh_q", 1.0) <= float(s["maximum_bh_fdr_q"])
        )
        c["economic_pass"] = bool(
            c.get("events", 0) >= int(e["minimum_trades"])
            and c.get(f"net_{pkey}_median_fold_bps", -np.inf) > float(e["minimum_primary_median_fold_net_bps"])
            and c.get(f"pf_{pkey}_median_fold", 0.0) >= float(e["minimum_primary_median_fold_pf"])
            and c.get(f"positive_fold_fraction_{pkey}", 0.0) >= float(e["minimum_primary_positive_fold_fraction"])
            and c.get(f"net_{hkey}_median_fold_bps", -np.inf) >= float(e["minimum_high_cost_median_fold_net_bps"])
            and c.get(f"mean_net_{pkey}_bps", -np.inf) > 0.0
            and c.get(f"mean_net_{pkey}_bps", -np.inf) > c.get("reversed_mean_net_primary_bps", np.inf)
            and c.get("event_mean_gross_bps", -np.inf) > c.get("placebo_mean_gross_bps", np.inf)
            and c.get("long", {}).get("trades", 0) >= int(e["minimum_long_trades"])
            and c.get("short", {}).get("trades", 0) >= int(e["minimum_short_trades"])
            and c.get("long", {}).get("mean_net_bps", -np.inf) > 0.0
            and c.get("short", {}).get("mean_net_bps", -np.inf) > 0.0
        )
        c["pre_family_pass"] = bool(c["state_pass"] and c["economic_pass"])
    lookup = {(c["event_type"], c["mode"], int(c["hold_minutes"])): c for c in cells}
    for c in cells:
        other_h = 180 if int(c["hold_minutes"]) == 60 else 60
        other = lookup[(c["event_type"], c["mode"], other_h)]
        c["other_horizon_consistent"] = bool(
            other.get("state_median_fold_excess_bps", -np.inf) >= 0.0
            and other.get(f"net_{pkey}_median_fold_bps", -np.inf) >= 0.0
        )
        c["full_development_pass"] = bool(c["pre_family_pass"] and c["other_horizon_consistent"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--gold", required=True)
    ap.add_argument("--cpi-html", required=True)
    ap.add_argument("--empsit-html", required=True)
    ap.add_argument("--fed-dir", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    gold = load_m15(Path(args.gold), cfg)
    dev = cfg["periods"]["development"]
    start_ts = pd.Timestamp(dev["start"])
    end_ts = pd.Timestamp(dev["end_exclusive"])
    d = gold.loc[(gold.index >= start_ts) & (gold.index < end_ts)].copy()
    if d.empty:
        raise SystemExit("no development bars")

    daily_counts = d.groupby(d.index.floor("D")).size()
    full_days = daily_counts[daily_counts >= 20]
    median_bars = float(full_days.median()) if len(full_days) else 0.0
    if median_bars < float(cfg["data_admission"]["minimum_median_bars_per_full_trading_day"]):
        raise SystemExit(f"intraday data not admissible: median full-day bars={median_bars}")

    cpi_html = Path(args.cpi_html).read_text(encoding="utf-8", errors="ignore")
    empsit_html = Path(args.empsit_html).read_text(encoding="utf-8", errors="ignore")
    fed_pages = {}
    for p in sorted(Path(args.fed_dir).glob("fomc_*.html")):
        m = re.search(r"(\d{4})", p.name)
        if m:
            fed_pages[int(m.group(1))] = p.read_text(encoding="utf-8", errors="ignore")
    events_all = build_events(cfg, cpi_html, empsit_html, fed_pages)
    events = events_all[(events_all["event_time"] >= start_ts) & (events_all["event_time"] < end_ts)].copy()

    cells = []
    for et in cfg["state_first"]["event_types"]:
        for mode in cfg["signal_definition"]["modes"]:
            for hold in cfg["signal_definition"]["holding_minutes"]:
                cells.append(evaluate_cell(d, events, str(et), str(mode), int(hold), start_ts, cfg))
    apply_gates(cells, cfg)

    passed = [c for c in cells if c.get("full_development_pass")]
    pkey = f"{float(cfg['execution']['primary_cost_bps']):g}"
    passed.sort(key=lambda c: (
        float(c.get("state_bh_q", 1.0)),
        -float(c.get("state_median_fold_excess_bps", -np.inf)),
        -float(c.get(f"positive_fold_fraction_{pkey}", -np.inf)),
        -float(c.get(f"net_{pkey}_median_fold_bps", -np.inf)),
        int(c["hold_minutes"]),
    ))
    selected = passed[: int(cfg["family_consistency"]["maximum_candidates"])]

    counts = events.groupby("event_type").size().to_dict() if len(events) else {}
    payload = {
        "schema_version": 1,
        "protocol": cfg["protocol_name"],
        "evidence_class": cfg["evidence_class"],
        "development_period": dev,
        "data_integrity": {
            "gold_rows_all_source": int(len(gold)),
            "development_bars": int(len(d)),
            "development_first_bar": str(d.index.min()),
            "development_last_bar": str(d.index.max()),
            "median_bars_per_full_day": median_bars,
            "event_counts": {str(k): int(v) for k, v in counts.items()},
            "total_events": int(len(events)),
        },
        "event_calendar": events.assign(event_time=events["event_time"].astype(str)).to_dict(orient="records"),
        "grid": {
            "cells_evaluated": int(len(cells)),
            "state_passes": int(sum(bool(c.get("state_pass")) for c in cells)),
            "economic_passes": int(sum(bool(c.get("economic_pass")) for c in cells)),
            "full_development_passes": int(len(passed)),
        },
        "cells": cells,
        "selected_candidates_for_separate_freeze": [c["candidate_id"] for c in selected],
        "locked_internal_validation_opened": False,
        "retrospective_extension_opened": False,
        "leverage_tested": False,
        "claims": cfg["claims"],
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(clean(payload), indent=2), encoding="utf-8")
    print(json.dumps(clean({
        "event_counts": payload["data_integrity"]["event_counts"],
        "cells": payload["grid"]["cells_evaluated"],
        "state_passes": payload["grid"]["state_passes"],
        "economic_passes": payload["grid"]["economic_passes"],
        "full_development_passes": payload["grid"]["full_development_passes"],
        "selected": payload["selected_candidates_for_separate_freeze"],
    }), indent=2))


if __name__ == "__main__":
    main()
