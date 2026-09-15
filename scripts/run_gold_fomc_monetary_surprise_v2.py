from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd


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


def rho(a, b) -> float:
    a = pd.Series(a, dtype=float)
    b = pd.Series(b, dtype=float)
    m = a.notna() & b.notna() & np.isfinite(a) & np.isfinite(b)
    if int(m.sum()) < 3:
        return float("nan")
    return float(a[m].rank(method="average").corr(b[m].rank(method="average")))


def stable_seed(base: int, text: str) -> int:
    h = hashlib.sha256(text.encode("utf-8")).digest()
    return int((base + int.from_bytes(h[:4], "big")) % (2**32 - 1))


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


def load_m15(path: Path, cfg: dict) -> pd.DataFrame:
    d = pd.read_csv(path)
    d.columns = [str(c).strip().lower() for c in d.columns]
    req = ["time", "open", "high", "low", "close", "tick_volume"]
    missing = [c for c in req if c not in d.columns]
    if missing:
        raise ValueError(f"missing XAU columns {missing}")
    d["time"] = pd.to_datetime(d["time"], utc=True, errors="coerce")
    for c in req[1:]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.dropna(subset=req)
    d = d[(d[["open", "high", "low", "close"]] > 0).all(axis=1)]
    d = d[d["tick_volume"] >= int(cfg["data_admission"]["minimum_tick_volume"])]
    d = d.drop_duplicates("time", keep="last").set_index("time").sort_index()
    return d[["open", "high", "low", "close", "tick_volume"]]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_surprises(path: Path, cfg: dict) -> pd.DataFrame:
    sc = cfg["surprise_source"]
    actual_hash = sha256(path)
    expected = str(sc["expected_sha256_from_pre_protocol_data_audit"])
    if actual_hash != expected:
        raise SystemExit(f"SF Fed workbook hash changed: expected {expected}, got {actual_hash}")
    d = pd.read_excel(path, sheet_name=sc["sheet"])
    needed = [sc["date_column"], sc["time_column"], sc["unscheduled_column"], sc["raw_surprise_column"], sc["orthogonalized_surprise_column"]]
    missing = [c for c in needed if c not in d.columns]
    if missing:
        raise SystemExit(f"SF Fed sheet missing columns {missing}")
    d[sc["date_column"]] = pd.to_datetime(d[sc["date_column"]], errors="coerce")
    for c in [sc["unscheduled_column"], sc["raw_surprise_column"], sc["orthogonalized_surprise_column"]]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.dropna(subset=[sc["date_column"], sc["unscheduled_column"]])
    d = d[d[sc["unscheduled_column"]] == 0].copy()
    # The audited 2018-2022 scheduled observations are all at 2:00pm.
    t = d[sc["time_column"]].astype(str).str.strip().str.lower().str.replace(" ", "", regex=False)
    d = d[t.isin(["2:00pm", "2pm", "14:00", "14:00:00"])].copy()
    tz = ZoneInfo(cfg["data_admission"]["required_fomc_timezone"])
    rows = []
    for _, r in d.iterrows():
        date = r[sc["date_column"]].date()
        local = datetime.combine(date, time(14, 0), tzinfo=tz)
        event_time = pd.Timestamp(local.astimezone(ZoneInfo("UTC")))
        rows.append({
            "date": pd.Timestamp(date),
            "event_time": event_time,
            "MPS": float(r[sc["raw_surprise_column"]]) if pd.notna(r[sc["raw_surprise_column"]]) else np.nan,
            "MPS_ORTH": float(r[sc["orthogonalized_surprise_column"]]) if pd.notna(r[sc["orthogonalized_surprise_column"]]) else np.nan,
        })
    out = pd.DataFrame(rows).drop_duplicates("event_time", keep="last").sort_values("event_time").reset_index(drop=True)
    return out


def exact_return(d: pd.DataFrame, event_time: pd.Timestamp, hold_minutes: int, side: int) -> float | None:
    entry = event_time + pd.Timedelta(minutes=30)
    exit_t = entry + pd.Timedelta(minutes=hold_minutes)
    if entry not in d.index or exit_t not in d.index:
        return None
    pe = float(d.loc[entry, "open"])
    px = float(d.loc[exit_t, "open"])
    if pe <= 0 or px <= 0:
        return None
    return float(side * (px / pe - 1.0) * 10000.0)


def placebo_values(d: pd.DataFrame, event_time: pd.Timestamp, hold_minutes: int, side: int, event_dates: set[pd.Timestamp]) -> list[float]:
    vals = []
    for days in (-7, 7):
        p_event = event_time + pd.Timedelta(days=days)
        if p_event.floor("D") in event_dates:
            continue
        x = exact_return(d, p_event, hold_minutes, side)
        if x is not None:
            vals.append(float(x))
    return vals


def directional_stats(tr: pd.DataFrame, net_col: str, side: int) -> dict:
    g = tr[tr["side"] == side]
    if g.empty:
        return {"trades": 0, "mean_net_bps": np.nan, "median_net_bps": np.nan, "win_rate": np.nan}
    x = g[net_col].to_numpy(float)
    return {
        "trades": int(len(g)),
        "mean_net_bps": float(np.mean(x)),
        "median_net_bps": float(np.median(x)),
        "win_rate": float(np.mean(x > 0)),
    }


def candidate_id(variant: str, hold: int) -> str:
    return f"fomc_surprise__{variant.lower()}__hold{hold}m"


def evaluate_cell(d: pd.DataFrame, events: pd.DataFrame, variant: str, hold: int, start_ts: pd.Timestamp, cfg: dict) -> dict:
    cid = candidate_id(variant, hold)
    cluster_days = int(cfg["state_first"]["dependence_cluster_calendar_days"])
    event_dates = set(events["event_time"].dt.floor("D"))
    rows = []
    for _, e in events.iterrows():
        surprise = e[variant]
        if not np.isfinite(surprise) or float(surprise) == 0.0:
            continue
        side = int(-np.sign(float(surprise)))
        gross = exact_return(d, e["event_time"], hold, side)
        if gross is None:
            continue
        pvals = placebo_values(d, e["event_time"], hold, side, event_dates)
        placebo = float(np.mean(pvals)) if pvals else np.nan
        excess = float(gross - placebo) if np.isfinite(placebo) else np.nan
        fold = int(np.floor((e["event_time"] - start_ts) / pd.Timedelta(days=cluster_days)))
        rows.append({
            "event_time": str(e["event_time"]),
            "fold": fold,
            "surprise": float(surprise),
            "abs_surprise": abs(float(surprise)),
            "side": side,
            "gross_bps": float(gross),
            "placebo_gross_bps": placebo,
            "state_excess_bps": excess,
        })
    tr = pd.DataFrame(rows)
    out = {"candidate_id": cid, "surprise_variant": variant, "hold_minutes": int(hold), "events": int(len(tr))}
    if tr.empty:
        return out

    sf = cfg["state_first"]
    state_rows = []
    for fid, g in tr.groupby("fold"):
        if len(g) < int(sf["minimum_events_per_scorable_fold"]):
            continue
        r = rho(g["abs_surprise"], g["gross_bps"])
        excess = g["state_excess_bps"].dropna().to_numpy(float)
        mean_excess = float(np.mean(excess)) if len(excess) else np.nan
        state_rows.append({"fold": int(fid), "events": int(len(g)), "spearman": r, "mean_excess_bps": mean_excess})
    rhos = [x["spearman"] for x in state_rows if np.isfinite(x["spearman"])]
    excesses = [x["mean_excess_bps"] for x in state_rows if np.isfinite(x["mean_excess_bps"])]
    out.update({
        "state_folds": int(len(state_rows)),
        "state_fold_rows": state_rows,
        "state_median_fold_spearman": float(np.median(rhos)) if rhos else np.nan,
        "state_positive_spearman_fold_fraction": float(np.mean(np.asarray(rhos) > 0)) if rhos else 0.0,
        "state_median_fold_excess_bps": float(np.median(excesses)) if excesses else np.nan,
        "state_positive_excess_fold_fraction": float(np.mean(np.asarray(excesses) > 0)) if excesses else 0.0,
        "state_sign_flip_p": sign_flip_pvalue(rhos, int(sf["fold_sign_flip_epochs"]), stable_seed(int(sf["fold_sign_flip_seed"]), cid)),
        "event_mean_gross_bps": float(tr["gross_bps"].mean()),
        "placebo_mean_gross_bps": float(tr["placebo_gross_bps"].dropna().mean()) if tr["placebo_gross_bps"].notna().any() else np.nan,
    })

    for cost in [float(x) for x in cfg["execution"]["round_trip_cost_bps"]]:
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
    out["long"] = directional_stats(tr, pcol, 1)
    out["short"] = directional_stats(tr, pcol, -1)
    out["trade_rows"] = rows
    return out


def apply_gates(cells: list[dict], cfg: dict) -> None:
    qvals = bh_qvalues([c.get("state_sign_flip_p", np.nan) for c in cells])
    sf = cfg["state_first"]
    eg = cfg["economic_gate"]
    pkey = f"{float(cfg['execution']['primary_cost_bps']):g}"
    hkey = f"{float(cfg['execution']['high_cost_bps']):g}"
    for c, q in zip(cells, qvals):
        c["state_bh_q"] = q
        c["state_pass"] = bool(
            c.get("state_folds", 0) >= int(sf["minimum_scorable_folds"])
            and c.get("state_median_fold_spearman", -np.inf) > float(sf["minimum_median_fold_spearman"])
            and c.get("state_positive_spearman_fold_fraction", 0.0) >= float(sf["minimum_positive_spearman_fold_fraction"])
            and c.get("state_median_fold_excess_bps", -np.inf) > float(sf["minimum_median_fold_excess_bps"])
            and c.get("state_positive_excess_fold_fraction", 0.0) >= float(sf["minimum_positive_excess_fold_fraction"])
            and c.get("state_bh_q", 1.0) <= float(sf["maximum_bh_fdr_q"])
        )
        c["economic_pass"] = bool(
            c.get("events", 0) >= int(eg["minimum_trades"])
            and c.get(f"net_{pkey}_median_fold_bps", -np.inf) > float(eg["minimum_primary_median_fold_net_bps"])
            and c.get(f"pf_{pkey}_median_fold", 0.0) >= float(eg["minimum_primary_median_fold_pf"])
            and c.get(f"positive_fold_fraction_{pkey}", 0.0) >= float(eg["minimum_primary_positive_fold_fraction"])
            and c.get(f"net_{hkey}_median_fold_bps", -np.inf) >= float(eg["minimum_high_cost_median_fold_net_bps"])
            and c.get(f"mean_net_{pkey}_bps", -np.inf) > 0.0
            and c.get(f"mean_net_{pkey}_bps", -np.inf) > c.get("reversed_mean_net_primary_bps", np.inf)
            and c.get("event_mean_gross_bps", -np.inf) > c.get("placebo_mean_gross_bps", np.inf)
            and c.get("long", {}).get("trades", 0) >= int(eg["minimum_long_trades"])
            and c.get("short", {}).get("trades", 0) >= int(eg["minimum_short_trades"])
            and c.get("long", {}).get("mean_net_bps", -np.inf) > 0.0
            and c.get("short", {}).get("mean_net_bps", -np.inf) > 0.0
        )
        c["pre_family_pass"] = bool(c["state_pass"] and c["economic_pass"])

    lookup = {(c["surprise_variant"], int(c["hold_minutes"])): c for c in cells}
    holds = sorted(int(x) for x in cfg["signal_grid"]["holding_minutes"])
    for c in cells:
        other_h = holds[1] if int(c["hold_minutes"]) == holds[0] else holds[0]
        other = lookup[(c["surprise_variant"], other_h)]
        c["other_horizon_consistent"] = bool(
            other.get("state_median_fold_excess_bps", -np.inf) >= 0.0
            and other.get(f"net_{pkey}_median_fold_bps", -np.inf) >= 0.0
        )
        c["full_development_pass"] = bool(c["pre_family_pass"] and c["other_horizon_consistent"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--gold", required=True)
    ap.add_argument("--surprises", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    gold = load_m15(Path(args.gold), cfg)
    events = load_surprises(Path(args.surprises), cfg)
    dev = cfg["periods"]["development"]
    start_ts = pd.Timestamp(dev["start"])
    end_ts = pd.Timestamp(dev["end_exclusive"])
    d = gold.loc[(gold.index >= start_ts) & (gold.index < end_ts)].copy()
    e = events[(events["event_time"] >= start_ts) & (events["event_time"] < end_ts)].copy()
    if d.empty or e.empty:
        raise SystemExit("empty development price or surprise data")

    cells = []
    for variant in cfg["signal_grid"]["surprise_variants"]:
        for hold in cfg["signal_grid"]["holding_minutes"]:
            cells.append(evaluate_cell(d, e, str(variant), int(hold), start_ts, cfg))
    apply_gates(cells, cfg)

    passed = [c for c in cells if c.get("full_development_pass")]
    pkey = f"{float(cfg['execution']['primary_cost_bps']):g}"
    passed.sort(key=lambda c: (
        float(c.get("state_bh_q", 1.0)),
        -float(c.get("state_median_fold_spearman", -np.inf)),
        -float(c.get("state_median_fold_excess_bps", -np.inf)),
        -float(c.get(f"positive_fold_fraction_{pkey}", -np.inf)),
        -float(c.get(f"net_{pkey}_median_fold_bps", -np.inf)),
        int(c["hold_minutes"]),
    ))
    selected = passed[: int(cfg["family_consistency"]["maximum_candidates"])]

    payload = {
        "schema_version": 1,
        "protocol": cfg["protocol_name"],
        "evidence_class": cfg["evidence_class"],
        "development_period": dev,
        "data_integrity": {
            "gold_rows_all_source": int(len(gold)),
            "development_bars": int(len(d)),
            "regular_fomc_rows_all_workbook": int(len(events)),
            "development_regular_fomc_events": int(len(e)),
            "development_raw_surprise_non_null": int(e["MPS"].notna().sum()),
            "development_orth_surprise_non_null": int(e["MPS_ORTH"].notna().sum()),
            "surprise_workbook_sha256": sha256(Path(args.surprises)),
        },
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
        "grid": payload["grid"],
        "data_integrity": payload["data_integrity"],
        "selected": payload["selected_candidates_for_separate_freeze"],
    }), indent=2))


if __name__ == "__main__":
    main()
