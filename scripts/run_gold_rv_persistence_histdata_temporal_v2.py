from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import timedelta, timezone
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo
import zipfile

import numpy as np
import pandas as pd

NY = ZoneInfo("America/New_York")
FIXED_EST = timezone(timedelta(hours=-5))


def clean(x):
    if x is pd.NaT or x is pd.NA:
        return None
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.bool_,)):
        return bool(x)
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
    digest = hashlib.sha256(f"{namespace}|{key}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % (2**32 - 1)


def spearman(x, y) -> float:
    xs = pd.Series(np.asarray(x, dtype=float))
    ys = pd.Series(np.asarray(y, dtype=float))
    m = xs.notna() & ys.notna() & np.isfinite(xs) & np.isfinite(ys)
    if int(m.sum()) < 3:
        return float("nan")
    return float(xs[m].rank(method="average").corr(ys[m].rank(method="average")))


def signflip_p(values, epochs: int, seed: int) -> float:
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    if not len(v):
        return 1.0
    observed = float(np.median(v))
    if observed <= 0:
        return 1.0
    rng = np.random.default_rng(seed)
    ge = done = 0
    while done < epochs:
        n = min(1000, epochs - done)
        signs = rng.choice(np.array([-1.0, 1.0]), size=(n, len(v)))
        ge += int(np.sum(np.median(signs * v, axis=1) >= observed - 1e-15))
        done += n
    return float((ge + 1) / (epochs + 1))


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify(path: Path, meta: dict) -> dict:
    size = path.stat().st_size
    sha = file_sha256(path)
    if size != int(meta["size_bytes"]):
        raise SystemExit(f"size mismatch {path.name}: {size}")
    if sha.lower() != str(meta["lfs_sha256"]).lower():
        raise SystemExit(f"sha256 mismatch {path.name}: {sha}")
    return {"path": str(path), "size_bytes": size, "sha256": sha, "verified": True}


def data_member(zf: zipfile.ZipFile) -> str:
    files = [n for n in zf.namelist() if not n.endswith("/") and "__macosx/" not in n.lower()]
    csvs = [n for n in files if n.lower().endswith(".csv")]
    if len(csvs) == 1:
        return csvs[0]
    if len(csvs) > 1:
        raise ValueError(f"multiple CSV members: {csvs}")
    txts = [n for n in files if n.lower().endswith(".txt")]
    if len(txts) == 1:
        return txts[0]
    raise ValueError(f"no unique HistData data member: {files}")


def load_zip(path: Path) -> tuple[pd.DataFrame, dict]:
    with zipfile.ZipFile(path) as zf:
        member = data_member(zf)
        raw = zf.read(member)
    d = pd.read_csv(
        BytesIO(raw), sep=";", header=None,
        names=["timestamp", "open", "high", "low", "close", "volume"],
        dtype=str, engine="python"
    )
    parsed = pd.to_datetime(d.timestamp.str.strip(), format="%Y%m%d %H%M%S", errors="coerce")
    if int(parsed.isna().sum()):
        raise ValueError("strict HistData timestamp parse failed")
    d["time"] = parsed.dt.tz_localize(FIXED_EST).dt.tz_convert("UTC")
    for c in ("open", "high", "low", "close", "volume"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    raw_rows = len(d)
    d = d.dropna(subset=["time", "open", "high", "low", "close"])
    d = d[(d[["open", "high", "low", "close"]] > 0).all(axis=1)]
    d = d[
        (d.high >= d[["open", "close"]].max(axis=1))
        & (d.low <= d[["open", "close"]].min(axis=1))
        & (d.high >= d.low)
    ]
    d = d.drop_duplicates("time", keep="last").sort_values("time").set_index("time")
    return d, {
        "archive": str(path), "member": member, "raw_rows": int(raw_rows),
        "valid_rows": int(len(d)), "first_utc": d.index.min(), "last_utc": d.index.max()
    }


def exact_window(d: pd.DataFrame, start: pd.Timestamp, periods: int):
    idx = pd.date_range(start, periods=periods, freq="1min", tz="UTC")
    x = d.reindex(idx)
    if x[["open", "high", "low", "close"]].isna().any().any():
        return None
    return x


def rv(prices) -> float:
    p = np.asarray(prices, dtype=float)
    if len(p) < 2 or np.any(~np.isfinite(p)) or np.any(p <= 0):
        return float("nan")
    r = np.diff(np.log(p))
    out = float(np.sqrt(np.sum(r * r)))
    return out if np.isfinite(out) and out > 0 else float("nan")


def observation(d: pd.DataFrame, t0: pd.Timestamp):
    pre = exact_window(d, t0 - pd.Timedelta(minutes=60), 60)
    fut = exact_window(d, t0, 60)
    pre_prices = exact_window(d, t0 - pd.Timedelta(minutes=61), 61)
    if pre is None or fut is None or pre_prices is None:
        return None
    pre_rv = rv(pre_prices.close.to_numpy(float))
    future_rv = rv(np.concatenate([[float(pre.close.iloc[-1])], fut.close.to_numpy(float)]))
    future_range = float(fut.high.max() - fut.low.min())
    if not np.isfinite(pre_rv) or not np.isfinite(future_rv) or future_range <= 0:
        return None
    local = t0.tz_convert(NY)
    return {
        "t0_utc": t0, "ny_date": str(local.date()), "anchor_hour": int(local.hour),
        "pre_rv": pre_rv, "future_rv": future_rv, "future_range": future_range
    }


def build_observations(d: pd.DataFrame, cfg: dict):
    grid, src = cfg["observation_grid"], cfg["source"]
    local = d.index.tz_convert(NY)
    warm = pd.Timestamp(src["scorer_warmup_start_ny"], tz=NY)
    end = pd.Timestamp(src["replication_end_exclusive_ny"], tz=NY)
    hours = np.array(grid["anchor_hours_local"], dtype=int)
    mask = (
        (local >= warm) & (local < end) & (local.weekday < 5)
        & (local.minute == int(grid["anchor_minute"])) & (local.second == 0)
        & np.isin(local.hour, hours)
    )
    rows = []
    for t0 in d.index[mask]:
        o = observation(d, pd.Timestamp(t0))
        if o is not None:
            rows.append(o)
    raw = pd.DataFrame(rows)
    if raw.empty:
        raise ValueError("no valid anchor observations")
    raw = raw.sort_values(["anchor_hour", "t0_utc"]).reset_index(drop=True)
    lookback = int(grid["same_clock_baseline_lookback_observations"])
    for col, base in (
        ("pre_rv", "baseline_pre_rv"),
        ("future_rv", "baseline_future_rv"),
        ("future_range", "baseline_future_range")
    ):
        raw[base] = raw.groupby("anchor_hour", group_keys=False)[col].transform(
            lambda s: s.shift(1).rolling(lookback, min_periods=lookback).median()
        )
    raw["pre_rv_ratio"] = raw.pre_rv / raw.baseline_pre_rv
    raw["future_rv_ratio"] = raw.future_rv / raw.baseline_future_rv
    raw["future_range_ratio"] = raw.future_range / raw.baseline_future_range
    raw = raw.replace([np.inf, -np.inf], np.nan)
    start = pd.Timestamp(src["replication_start_ny"], tz=NY)
    end = pd.Timestamp(src["replication_end_exclusive_ny"], tz=NY)
    local_t0 = raw.t0_utc.map(lambda x: pd.Timestamp(x).tz_convert(NY))
    scored = raw.loc[(local_t0 >= start) & (local_t0 < end)].copy()
    scored = scored.dropna(subset=["pre_rv_ratio", "future_rv_ratio", "future_range_ratio"])
    scored = scored[(scored.pre_rv_ratio > 0) & (scored.future_rv_ratio > 0) & (scored.future_range_ratio > 0)]
    if scored.empty:
        raise ValueError("no observations after causal warmup")
    return raw.sort_values("t0_utc").reset_index(drop=True), scored.sort_values("t0_utc").reset_index(drop=True)


def daily_effects(obs: pd.DataFrame, target: str, min_anchors: int) -> pd.DataFrame:
    rows = []
    for day, g in obs.groupby("ny_date", sort=True):
        q = g.dropna(subset=["pre_rv_ratio", target])
        if len(q) < min_anchors:
            continue
        effect = spearman(q.pre_rv_ratio.to_numpy(float), q[target].to_numpy(float))
        if np.isfinite(effect):
            rows.append({"ny_date": day, "n": int(len(q)), "effect": float(effect)})
    return pd.DataFrame(rows)


def anchor_effects(obs: pd.DataFrame, min_n: int) -> list[dict]:
    out = []
    for hour, g in obs.groupby("anchor_hour", sort=True):
        q = g.dropna(subset=["pre_rv_ratio", "future_rv_ratio"])
        effect = spearman(q.pre_rv_ratio, q.future_rv_ratio) if len(q) >= min_n else np.nan
        out.append({"anchor_hour": int(hour), "n": int(len(q)), "effect": effect, "eligible": bool(len(q) >= min_n)})
    return out


def quality(d: pd.DataFrame, daily: pd.DataFrame) -> dict:
    w = d[["close"]].copy()
    w["prev_time"] = w.index.to_series().shift(1)
    w["prev_close"] = w.close.shift(1)
    contiguous = (w.index.to_series() - w.prev_time) == pd.Timedelta(minutes=1)
    w["abs_log_return"] = np.where(
        contiguous & (w.prev_close > 0) & (w.close > 0), np.abs(np.log(w.close / w.prev_close)), np.nan
    )
    top = w.dropna(subset=["abs_log_return"]).nlargest(5, "abs_log_return")
    dm = daily.set_index("ny_date").effect.to_dict() if len(daily) else {}
    rows = []
    for ts, r in top.iterrows():
        day = str(pd.Timestamp(ts).tz_convert(NY).date())
        rows.append({
            "timestamp_utc": pd.Timestamp(ts), "ny_date": day,
            "abs_log_return": float(r.abs_log_return), "daily_primary_effect_if_scorable": dm.get(day)
        })
    return {"max_abs_one_minute_log_return": float(top.abs_log_return.max()) if len(top) else np.nan, "top_five": rows}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--warmup-zip", required=True)
    ap.add_argument("--replication-zip", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--daily-output")
    ap.add_argument("--anchor-output")
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text())
    if cfg.get("protocol_status") != "later_historical_temporal_replication_frozen":
        raise SystemExit("protocol not frozen")
    if cfg.get("economic_scoring_enabled") is not False:
        raise SystemExit("economics must remain disabled")
    if cfg["parent_candidate"]["candidate_id"] != "rv_persistence" or cfg["parent_candidate"]["frozen_sign"] != "positive":
        raise SystemExit("unexpected candidate")
    if cfg["parent_candidate"]["selection_or_retuning_after_v1"] is not False:
        raise SystemExit("post-v1 selection/retuning prohibited")

    warm_path, rep_path = Path(args.warmup_zip), Path(args.replication_zip)
    warm_ver = verify(warm_path, cfg["source"]["warmup_archive"])
    rep_ver = verify(rep_path, cfg["source"]["replication_archive"])
    dw, qw = load_zip(warm_path)
    dr, qr = load_zip(rep_path)
    d = pd.concat([dw, dr]).sort_index()
    d = d[~d.index.duplicated(keep="last")]

    allowed_years = {int(cfg["source"]["warmup_archive"]["year"]), int(cfg["source"]["replication_archive"]["year"])}
    years = set(int(y) for y in d.index.year.unique())
    if not years.issubset(allowed_years) or int(cfg["source"]["replication_archive"]["year"]) not in years:
        raise SystemExit(f"unexpected source years: {sorted(years)}")

    raw, obs = build_observations(d, cfg)
    start = pd.Timestamp(cfg["source"]["replication_start_ny"], tz=NY)
    end = pd.Timestamp(cfg["source"]["replication_end_exclusive_ny"], tz=NY)
    local_obs = obs.t0_utc.map(lambda x: pd.Timestamp(x).tz_convert(NY))
    if not bool(((local_obs >= start) & (local_obs < end)).all()):
        raise SystemExit("non-replication-period anchor entered inference")

    min_anchors = int(cfg["observation_grid"]["minimum_daily_anchor_count_for_inference"])
    daily = daily_effects(obs, "future_rv_ratio", min_anchors)
    secondary = daily_effects(obs, "future_range_ratio", min_anchors)
    if daily.empty:
        raise SystemExit("no scorable replication dates")

    effects = daily.effect.to_numpy(float)
    primary = float(np.median(effects))
    positive_fraction = float(np.mean(effects > 0))
    p = signflip_p(
        effects, int(cfg["statistics"]["permutation_epochs"]),
        stable_seed(cfg["statistics"]["random_seed_namespace"], cfg["parent_candidate"]["candidate_id"])
    )
    secondary_median = float(np.median(secondary.effect.to_numpy(float))) if len(secondary) else np.nan

    split = pd.Timestamp(cfg["source"]["half_split_ny"])
    dates = pd.to_datetime(daily.ny_date)
    first = daily.loc[dates < split, "effect"].to_numpy(float)
    second = daily.loc[dates >= split, "effect"].to_numpy(float)
    first_median = float(np.median(first)) if len(first) else np.nan
    second_median = float(np.median(second)) if len(second) else np.nan

    gate = cfg["replication_gate"]
    anchors = anchor_effects(obs, int(gate["minimum_anchor_slot_observations"]))
    positive_slots = sum(1 for r in anchors if r["eligible"] and np.isfinite(r["effect"]) and r["effect"] > 0)
    gate_results = {
        "minimum_scorable_dates": len(daily) >= int(gate["minimum_scorable_dates"]),
        "minimum_median_daily_effect": primary >= float(gate["minimum_median_daily_effect"]),
        "minimum_daily_positive_fraction": positive_fraction >= float(gate["minimum_daily_positive_fraction"]),
        "minimum_positive_anchor_slots": positive_slots >= int(gate["minimum_positive_anchor_slots"]),
        "first_half_positive": np.isfinite(first_median) and first_median > 0,
        "second_half_positive": np.isfinite(second_median) and second_median > 0,
        "secondary_range_positive": np.isfinite(secondary_median) and secondary_median > 0,
        "primary_p_max": p <= float(gate["primary_p_max"])
    }
    passed = bool(all(gate_results.values()))

    result = {
        "protocol_id": cfg["protocol_id"],
        "stage": "independent_source_later_historical_temporal_state_replication",
        "candidate_id": cfg["parent_candidate"]["candidate_id"],
        "candidate_sign": cfg["parent_candidate"]["frozen_sign"],
        "replication_classification": cfg["replication_classification"],
        "economic_scoring_run": False,
        "directional_scoring_run": False,
        "prospective_future_oos_claim": False,
        "source_verification": {"warmup": warm_ver, "replication": rep_ver, "warmup_parse": qw, "replication_parse": qr},
        "combined_input_rows": int(len(d)),
        "combined_input_start": d.index.min(),
        "combined_input_end": d.index.max(),
        "raw_anchor_observations_including_warmup": int(len(raw)),
        "replication_observations": int(len(obs)),
        "first_scorable_anchor_utc": obs.t0_utc.min(),
        "last_scorable_anchor_utc": obs.t0_utc.max(),
        "scorable_dates": int(len(daily)),
        "primary_median_daily_spearman": primary,
        "daily_positive_fraction": positive_fraction,
        "one_sided_positive_signflip_p": p,
        "first_half_dates": int(len(first)),
        "first_half_median_daily_spearman": first_median,
        "second_half_dates": int(len(second)),
        "second_half_median_daily_spearman": second_median,
        "secondary_range_median_daily_spearman": secondary_median,
        "anchor_effects": anchors,
        "positive_anchor_slots": int(positive_slots),
        "gate_results": gate_results,
        "replication_pass": passed,
        "data_quality_diagnostics": quality(d, daily),
        "claim_boundary": {
            "later_historical_oos": True,
            "prospective_future_oos": False,
            "directional_edge": False,
            "economic_edge": False,
            "leverage_authorized": False,
            "live_enabled": False
        }
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(clean(result), indent=2, sort_keys=True) + "\n")
    if args.daily_output:
        pth = Path(args.daily_output); pth.parent.mkdir(parents=True, exist_ok=True); daily.to_csv(pth, index=False)
    if args.anchor_output:
        pth = Path(args.anchor_output); pth.parent.mkdir(parents=True, exist_ok=True); pd.DataFrame(anchors).to_csv(pth, index=False)
    print(json.dumps(clean(result), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
