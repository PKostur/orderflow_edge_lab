from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd


HORIZONS = (30, 60, 120)
NY = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


def clean(x):
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating, float)):
        v = float(x)
        return v if math.isfinite(v) else None
    if isinstance(x, pd.Timestamp):
        return x.isoformat()
    if isinstance(x, dict):
        return {str(k): clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean(v) for v in x]
    return x


def stable_seed(namespace: str, key: str) -> int:
    h = hashlib.sha256(f"{namespace}|{key}".encode("utf-8")).digest()
    return int.from_bytes(h[:8], "big") % (2**32 - 1)


def bh_qvalues(p_values: list[float]) -> list[float]:
    p = np.asarray(p_values, dtype=float)
    n = len(p)
    order = np.argsort(p)
    ranked = p[order]
    q = ranked * n / np.arange(1, n + 1)
    q = np.minimum.accumulate(q[::-1])[::-1]
    q = np.clip(q, 0.0, 1.0)
    out = np.empty(n, dtype=float)
    out[order] = q
    return out.tolist()


def spearman(x: np.ndarray, y: np.ndarray) -> float:
    x = pd.Series(x, dtype=float)
    y = pd.Series(y, dtype=float)
    m = x.notna() & y.notna() & np.isfinite(x) & np.isfinite(y)
    if int(m.sum()) < 3:
        return float("nan")
    xr = x[m].rank(method="average")
    yr = y[m].rank(method="average")
    return float(xr.corr(yr))


def signflip_median_p(values: np.ndarray, epochs: int, seed: int) -> float:
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    if len(v) == 0:
        return 1.0
    observed = abs(float(np.median(v)))
    rng = np.random.default_rng(seed)
    ge = 0
    done = 0
    chunk = 2000
    while done < epochs:
        n = min(chunk, epochs - done)
        signs = rng.choice(np.array([-1.0, 1.0]), size=(n, len(v)))
        stats = np.abs(np.median(signs * v, axis=1))
        ge += int(np.sum(stats >= observed - 1e-15))
        done += n
    return float((ge + 1) / (epochs + 1))


def label_permutation_p(values: np.ndarray, labels: np.ndarray, epochs: int, seed: int) -> float:
    v = np.asarray(values, dtype=float)
    lab = np.asarray(labels, dtype=int)
    m = np.isfinite(v) & np.isin(lab, [-1, 1])
    v = v[m]
    lab = lab[m]
    if np.sum(lab == 1) == 0 or np.sum(lab == -1) == 0:
        return 1.0
    observed = abs(float(np.median(v[lab == 1]) - np.median(v[lab == -1])))
    rng = np.random.default_rng(seed)
    ge = 0
    for _ in range(epochs):
        perm = rng.permutation(lab)
        stat = abs(float(np.median(v[perm == 1]) - np.median(v[perm == -1])))
        ge += int(stat >= observed - 1e-15)
    return float((ge + 1) / (epochs + 1))


def correlation_permutation_p(x: np.ndarray, y: np.ndarray, epochs: int, seed: int) -> float:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    m = np.isfinite(x) & np.isfinite(y)
    x = x[m]
    y = y[m]
    if len(x) < 3:
        return 1.0
    observed = abs(spearman(x, y))
    rng = np.random.default_rng(seed)
    ge = 0
    for _ in range(epochs):
        stat = abs(spearman(x, rng.permutation(y)))
        ge += int(stat >= observed - 1e-15)
    return float((ge + 1) / (epochs + 1))


def load_gold(path: Path) -> pd.DataFrame:
    d = pd.read_csv(path)
    d.columns = [str(c).strip().lower() for c in d.columns]
    required = {"time", "open", "high", "low", "close"}
    missing = required.difference(d.columns)
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")
    d["time"] = pd.to_datetime(d["time"], utc=True, errors="coerce")
    for c in ("open", "high", "low", "close"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    if "tick_volume" in d.columns:
        d["tick_volume"] = pd.to_numeric(d["tick_volume"], errors="coerce")
    d = d.dropna(subset=["time", "open", "high", "low", "close"])
    d = d[(d[["open", "high", "low", "close"]] > 0).all(axis=1)]
    d = d[(d.high >= d[["open", "close"]].max(axis=1)) & (d.low <= d[["open", "close"]].min(axis=1))]
    d = d.drop_duplicates("time", keep="last").sort_values("time").set_index("time")
    return d


def load_calendar(path: Path, cfg: dict) -> pd.DataFrame:
    cal = pd.read_csv(path, dtype=str)
    required = {"event_id", "event_type", "date_local", "time_local", "timezone", "official_source"}
    missing = required.difference(cal.columns)
    if missing:
        raise ValueError(f"calendar missing columns: {sorted(missing)}")
    if len(cal) != int(cfg["event_calendar"]["expected_total_events"]):
        raise ValueError(f"calendar has {len(cal)} rows, expected {cfg['event_calendar']['expected_total_events']}")
    expected = {k: int(v["expected_count"]) for k, v in cfg["event_calendar"]["event_types"].items()}
    actual = cal.event_type.value_counts().to_dict()
    if actual != expected:
        raise ValueError(f"event type counts mismatch: actual={actual}, expected={expected}")
    local = pd.to_datetime(cal.date_local + " " + cal.time_local, errors="raise")
    cal["event_time_local"] = local.dt.tz_localize(NY)
    cal["event_time_utc"] = cal.event_time_local.dt.tz_convert(UTC)
    return cal.sort_values("event_time_utc").reset_index(drop=True)


def exact_close(d: pd.DataFrame, ts: pd.Timestamp) -> float:
    if ts not in d.index:
        return float("nan")
    return float(d.at[ts, "close"])


def exact_window(d: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, expected: int) -> pd.DataFrame | None:
    x = d.loc[(d.index >= start) & (d.index <= end)]
    if len(x) != expected:
        return None
    expected_idx = pd.date_range(start, periods=expected, freq="1min", tz="UTC")
    if not x.index.equals(expected_idx):
        return None
    return x


def build_daily_ranges(d: pd.DataFrame) -> pd.DataFrame:
    local = d.copy()
    local["ny_date"] = local.index.tz_convert(NY).date
    daily = local.groupby("ny_date", sort=True).agg(high=("high", "max"), low=("low", "min"), bars=("close", "size"))
    daily["range"] = daily.high - daily.low
    return daily


def prior_daily_range_median(daily: pd.DataFrame, local_date, n_days: int) -> float:
    prior = daily.loc[daily.index < local_date, "range"].dropna().tail(n_days)
    if len(prior) < n_days:
        return float("nan")
    med = float(prior.median())
    return med if med > 0 else float("nan")


def state_observation(d: pd.DataFrame, daily: pd.DataFrame, t0: pd.Timestamp, cfg: dict, include_features: bool) -> dict | None:
    pre_ts = t0 - pd.Timedelta(minutes=1)
    initial_ts = t0 + pd.Timedelta(minutes=14)
    pre_price = exact_close(d, pre_ts)
    initial_price = exact_close(d, initial_ts)
    if not np.isfinite(pre_price) or not np.isfinite(initial_price):
        return None

    scale_minutes = int(cfg["event_state_definition"]["pre_event_scale_minutes"])
    pre_window = exact_window(d, t0 - pd.Timedelta(minutes=scale_minutes), pre_ts, scale_minutes)
    if pre_window is None:
        return None
    pre_range = float(pre_window.high.max() - pre_window.low.min())
    min_frac = float(cfg["event_state_definition"]["minimum_scale_price_fraction"])
    if not np.isfinite(pre_range) or pre_range <= pre_price * min_frac:
        return None

    initial = float(initial_price - pre_price)
    direction = int(np.sign(initial))
    if direction == 0:
        return None

    scores = {}
    future_prices = {}
    for h in HORIZONS:
        future_ts = initial_ts + pd.Timedelta(minutes=h)
        px = exact_close(d, future_ts)
        if not np.isfinite(px):
            scores[h] = np.nan
            future_prices[h] = np.nan
        else:
            future_prices[h] = px
            scores[h] = float(direction * (px - initial_price) / pre_range)

    if not all(np.isfinite(scores[h]) for h in HORIZONS):
        return None

    out = {
        "t0_utc": t0,
        "pre_price": pre_price,
        "initial_price": initial_price,
        "pre_range": pre_range,
        "initial_reaction": initial,
        "initial_direction": direction,
        "shock_size": abs(initial) / pre_range,
        **{f"continuation_{h}": scores[h] for h in HORIZONS},
    }

    if include_features:
        old_ts = t0 - pd.Timedelta(minutes=241)
        old_price = exact_close(d, old_ts)
        if np.isfinite(old_price) and old_price > 0:
            ret4h = pre_price / old_price - 1.0
            out["pre4h_return"] = float(ret4h)
            out["trend_alignment"] = int(direction * np.sign(ret4h)) if ret4h != 0 else 0
        else:
            out["pre4h_return"] = np.nan
            out["trend_alignment"] = 0

        local_date = t0.tz_convert(NY).date()
        med_daily = prior_daily_range_median(daily, local_date, int(cfg["pre_existing_features"]["compression"]["history_days"]))
        out["prior20_daily_range_median"] = med_daily
        out["compression"] = pre_range / med_daily if np.isfinite(med_daily) and med_daily > 0 else np.nan
    return out


def assemble_events(d: pd.DataFrame, cal: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    daily = build_daily_ranges(d)
    event_dates = set(cal.date_local.astype(str))
    placebo_offsets = [int(x) for x in cfg["matched_placebo_control"]["offset_calendar_days"]]
    rows = []
    for r in cal.itertuples(index=False):
        t0 = pd.Timestamp(r.event_time_utc)
        obs = state_observation(d, daily, t0, cfg, include_features=True)
        if obs is None:
            rows.append({
                "event_id": r.event_id,
                "event_type": r.event_type,
                "date_local": r.date_local,
                "time_local": r.time_local,
                "event_scorable": False,
            })
            continue
        row = {
            "event_id": r.event_id,
            "event_type": r.event_type,
            "date_local": r.date_local,
            "time_local": r.time_local,
            "event_scorable": True,
            **obs,
        }
        valid_placebos = []
        for offset in placebo_offsets:
            p_local = pd.Timestamp(r.event_time_local) + pd.Timedelta(days=offset)
            p_date = str(p_local.date())
            if p_date in event_dates:
                continue
            p_utc = p_local.tz_convert(UTC)
            po = state_observation(d, daily, p_utc, cfg, include_features=False)
            if po is not None:
                valid_placebos.append((offset, po))
        row["valid_placebo_count"] = len(valid_placebos)
        for h in HORIZONS:
            vals = [po[f"continuation_{h}"] for _, po in valid_placebos]
            placebo = float(np.median(vals)) if vals else np.nan
            row[f"placebo_continuation_{h}"] = placebo
            row[f"excess_continuation_{h}"] = row[f"continuation_{h}"] - placebo if np.isfinite(placebo) else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def horizon_signs(metrics: dict[int, float]) -> tuple[int, int]:
    signs = [int(np.sign(v)) for v in metrics.values() if np.isfinite(v) and v != 0]
    if not signs:
        return 0, 0
    primary = int(np.sign(metrics[60])) if np.isfinite(metrics[60]) else 0
    agree = sum(s == primary for s in signs) if primary else 0
    return primary, agree


def event_type_test(events: pd.DataFrame, event_type: str, cfg: dict) -> dict:
    g = events[(events.event_scorable == True) & (events.event_type == event_type)].copy()  # noqa: E712
    excess_metrics = {}
    horizon_details = {}
    epochs = int(cfg["statistics"]["permutation_epochs"])
    ns = cfg["statistics"]["random_seed_namespace"]
    for h in HORIZONS:
        col = f"excess_continuation_{h}"
        vals = pd.to_numeric(g[col], errors="coerce").dropna().to_numpy(float)
        med = float(np.median(vals)) if len(vals) else np.nan
        excess_metrics[h] = med
        horizon_details[str(h)] = {
            "scorable_excess_events": int(len(vals)),
            "median_excess": med,
            "mean_excess": float(np.mean(vals)) if len(vals) else np.nan,
            "positive_fraction": float(np.mean(vals > 0)) if len(vals) else np.nan,
            "negative_fraction": float(np.mean(vals < 0)) if len(vals) else np.nan,
            "reversed_control_median": -med if np.isfinite(med) else np.nan,
            "two_sided_signflip_p": signflip_median_p(vals, epochs, stable_seed(ns, f"{event_type}|{h}")),
        }
    primary_sign, same_sign_horizons = horizon_signs(excess_metrics)
    primary_vals = pd.to_numeric(g["excess_continuation_60"], errors="coerce").dropna().to_numpy(float)
    directional_consistency = float(np.mean(np.sign(primary_vals) == primary_sign)) if len(primary_vals) and primary_sign else 0.0
    event_scorable = int(len(g))
    placebo_valid = int(g["excess_continuation_60"].notna().sum()) if event_scorable else 0
    return {
        "id": f"{event_type}_excess_continuation",
        "family": "event_type_base",
        "event_type": event_type,
        "event_scorable": event_scorable,
        "primary_placebo_valid": placebo_valid,
        "primary_placebo_valid_fraction": float(placebo_valid / event_scorable) if event_scorable else 0.0,
        "horizons": horizon_details,
        "primary_effect": excess_metrics[60],
        "primary_sign": primary_sign,
        "same_sign_horizons": int(same_sign_horizons),
        "directional_consistency": directional_consistency,
        "primary_p": horizon_details["60"]["two_sided_signflip_p"],
    }


def trend_alignment_test(events: pd.DataFrame, cfg: dict) -> dict:
    g = events[(events.event_scorable == True) & events.trend_alignment.isin([-1, 1])].copy()  # noqa: E712
    details = {}
    effects = {}
    epochs = int(cfg["statistics"]["permutation_epochs"])
    ns = cfg["statistics"]["random_seed_namespace"]
    for h in HORIZONS:
        y = pd.to_numeric(g[f"continuation_{h}"], errors="coerce").to_numpy(float)
        lab = pd.to_numeric(g.trend_alignment, errors="coerce").to_numpy(int)
        m = np.isfinite(y) & np.isin(lab, [-1, 1])
        y = y[m]
        lab = lab[m]
        aligned = y[lab == 1]
        opposed = y[lab == -1]
        effect = float(np.median(aligned) - np.median(opposed)) if len(aligned) and len(opposed) else np.nan
        effects[h] = effect
        details[str(h)] = {
            "aligned_n": int(len(aligned)),
            "opposed_n": int(len(opposed)),
            "aligned_median": float(np.median(aligned)) if len(aligned) else np.nan,
            "opposed_median": float(np.median(opposed)) if len(opposed) else np.nan,
            "median_difference": effect,
            "two_sided_label_permutation_p": label_permutation_p(y, lab, epochs, stable_seed(ns, f"trend_alignment|{h}")),
        }
    sign, agree = horizon_signs(effects)
    subtype = {}
    robust_types = 0
    for typ in ("cpi", "employment", "fomc"):
        q = g[g.event_type == typ]
        a = q[q.trend_alignment == 1].continuation_60.to_numpy(float)
        o = q[q.trend_alignment == -1].continuation_60.to_numpy(float)
        effect = float(np.median(a) - np.median(o)) if len(a) and len(o) else np.nan
        eligible = len(a) >= 8 and len(o) >= 8
        agrees = bool(eligible and sign != 0 and np.sign(effect) == sign)
        robust_types += int(agrees)
        subtype[typ] = {"aligned_n": int(len(a)), "opposed_n": int(len(o)), "effect": effect, "eligible_for_robustness": eligible, "agrees_with_primary_sign": agrees}
    return {
        "id": "trend_alignment_effect",
        "family": "pre_existing_regime",
        "event_type": "all",
        "horizons": details,
        "primary_effect": effects[60],
        "primary_sign": sign,
        "same_sign_horizons": int(agree),
        "event_type_robustness": subtype,
        "robust_event_types": int(robust_types),
        "primary_p": details["60"]["two_sided_label_permutation_p"],
    }


def continuous_test(events: pd.DataFrame, feature: str, hyp_id: str, family: str, cfg: dict) -> dict:
    g = events[events.event_scorable == True].copy()  # noqa: E712
    details = {}
    effects = {}
    epochs = int(cfg["statistics"]["permutation_epochs"])
    ns = cfg["statistics"]["random_seed_namespace"]
    for h in HORIZONS:
        x = pd.to_numeric(g[feature], errors="coerce").to_numpy(float)
        y = pd.to_numeric(g[f"continuation_{h}"], errors="coerce").to_numpy(float)
        m = np.isfinite(x) & np.isfinite(y)
        x = x[m]
        y = y[m]
        rho = spearman(x, y)
        effects[h] = rho
        details[str(h)] = {
            "n": int(len(x)),
            "spearman": rho,
            "two_sided_permutation_p": correlation_permutation_p(x, y, epochs, stable_seed(ns, f"{hyp_id}|{h}")),
        }
    sign, agree = horizon_signs(effects)
    subtype = {}
    robust_types = 0
    for typ in ("cpi", "employment", "fomc"):
        q = g[g.event_type == typ]
        x = pd.to_numeric(q[feature], errors="coerce").to_numpy(float)
        y = pd.to_numeric(q.continuation_60, errors="coerce").to_numpy(float)
        m = np.isfinite(x) & np.isfinite(y)
        x = x[m]
        y = y[m]
        rho = spearman(x, y) if len(x) >= 3 else np.nan
        eligible = len(x) >= 8
        agrees = bool(eligible and sign != 0 and np.isfinite(rho) and np.sign(rho) == sign)
        robust_types += int(agrees)
        subtype[typ] = {"n": int(len(x)), "spearman": rho, "eligible_for_robustness": eligible, "agrees_with_primary_sign": agrees}
    return {
        "id": hyp_id,
        "family": family,
        "event_type": "all",
        "feature": feature,
        "horizons": details,
        "primary_effect": effects[60],
        "primary_sign": sign,
        "same_sign_horizons": int(agree),
        "event_type_robustness": subtype,
        "robust_event_types": int(robust_types),
        "primary_p": details["60"]["two_sided_permutation_p"],
    }


def apply_gates(results: list[dict], cfg: dict) -> list[dict]:
    qvals = bh_qvalues([float(r["primary_p"]) for r in results])
    for r, q in zip(results, qvals):
        r["primary_fdr_q"] = float(q)
        same_h = int(r["same_sign_horizons"])
        if r["family"] == "event_type_base":
            h = r["horizons"]["60"]
            passed = (
                h["scorable_excess_events"] >= int(cfg["state_gate"]["event_type_min_events"])
                and r["primary_placebo_valid_fraction"] >= float(cfg["state_gate"]["event_type_min_valid_placebo_fraction"])
                and abs(float(r["primary_effect"])) >= float(cfg["state_gate"]["event_type_min_abs_median_excess"])
                and float(r["directional_consistency"]) >= float(cfg["state_gate"]["event_type_min_direction_consistency"])
                and same_h >= int(cfg["state_gate"]["minimum_same_sign_horizons"])
                and q <= float(cfg["state_gate"]["fdr_q_max"])
            )
        elif r["id"] == "trend_alignment_effect":
            h = r["horizons"]["60"]
            passed = (
                h["aligned_n"] >= int(cfg["state_gate"]["regime_min_group_events"])
                and h["opposed_n"] >= int(cfg["state_gate"]["regime_min_group_events"])
                and abs(float(r["primary_effect"])) >= float(cfg["state_gate"]["regime_min_abs_median_difference"])
                and same_h >= int(cfg["state_gate"]["minimum_same_sign_horizons"])
                and r["robust_event_types"] >= 2
                and q <= float(cfg["state_gate"]["fdr_q_max"])
            )
        else:
            h = r["horizons"]["60"]
            passed = (
                h["n"] >= int(cfg["state_gate"]["continuous_min_events"])
                and abs(float(r["primary_effect"])) >= float(cfg["state_gate"]["continuous_min_abs_spearman"])
                and same_h >= int(cfg["state_gate"]["minimum_same_sign_horizons"])
                and r["robust_event_types"] >= 2
                and q <= float(cfg["state_gate"]["fdr_q_max"])
            )
        r["state_pass"] = bool(passed)
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--calendar", required=True)
    ap.add_argument("--gold", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    if cfg.get("state_scoring_enabled") is not True or cfg.get("economic_scoring_enabled") is not False:
        raise SystemExit("state/economic gate inconsistent with frozen protocol")
    if cfg["evidence_boundary"].get("validation_opened") is not False:
        raise SystemExit("locked validation is not sealed")

    gold = load_gold(Path(args.gold))
    cal = load_calendar(Path(args.calendar), cfg)

    development_end = pd.Timestamp(cfg["evidence_boundary"]["development_end_exclusive"], tz="UTC")
    if gold.index.max() >= development_end:
        raise SystemExit("input contains post-development data; workflow must physically truncate before scorer")
    if cal.event_time_utc.max() >= development_end:
        raise SystemExit("calendar leaks locked validation")

    events = assemble_events(gold, cal, cfg)
    results = [
        event_type_test(events, "cpi", cfg),
        event_type_test(events, "employment", cfg),
        event_type_test(events, "fomc", cfg),
        trend_alignment_test(events, cfg),
        continuous_test(events, "compression", "pre_event_compression_effect", "pre_existing_regime", cfg),
        continuous_test(events, "shock_size", "initial_shock_size_effect", "reaction_state", cfg),
    ]
    results = apply_gates(results, cfg)
    candidates = [r["id"] for r in results if r["state_pass"]]

    event_records = []
    for _, r in events.iterrows():
        event_records.append({k: clean(v) for k, v in r.to_dict().items()})

    output = {
        "protocol_id": cfg["protocol_id"],
        "stage": "development_state_only",
        "development_period": [cfg["evidence_boundary"]["development_start"], cfg["evidence_boundary"]["development_end_exclusive"]],
        "locked_validation_period": [cfg["evidence_boundary"]["locked_historical_validation_start"], cfg["evidence_boundary"]["locked_historical_validation_end_exclusive"]],
        "holdout_opened": False,
        "economic_scoring_run": False,
        "gold_source": cfg["gold_source"],
        "input_rows": int(len(gold)),
        "input_start": gold.index.min().isoformat(),
        "input_end": gold.index.max().isoformat(),
        "calendar_events": int(len(cal)),
        "scorable_events": int(events.event_scorable.fillna(False).sum()),
        "primary_hypothesis_count": len(results),
        "state_pass_count": len(candidates),
        "state_candidates": candidates,
        "hypotheses": results,
        "events": event_records,
        "claims": {
            "state_edge_established": bool(candidates),
            "executable_edge_established": False,
            "profitable_edge_established": False,
            "verified_future_oos": False,
            "leverage_authorized": False,
            "live_enabled": False,
        },
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(clean(output), indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({
        "calendar_events": output["calendar_events"],
        "scorable_events": output["scorable_events"],
        "state_pass_count": output["state_pass_count"],
        "state_candidates": output["state_candidates"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
