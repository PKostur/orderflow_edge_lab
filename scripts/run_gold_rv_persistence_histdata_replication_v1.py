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
    digest = hashlib.sha256(f"{namespace}|{key}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % (2**32 - 1)


def spearman(x: np.ndarray, y: np.ndarray) -> float:
    xs = pd.Series(np.asarray(x, dtype=float))
    ys = pd.Series(np.asarray(y, dtype=float))
    m = xs.notna() & ys.notna() & np.isfinite(xs) & np.isfinite(ys)
    if int(m.sum()) < 3:
        return float("nan")
    xr = xs[m].rank(method="average")
    yr = ys[m].rank(method="average")
    return float(xr.corr(yr))


def positive_signflip_p(values: np.ndarray, epochs: int, seed: int) -> float:
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    if len(v) == 0:
        return 1.0
    observed = float(np.median(v))
    if observed <= 0:
        return 1.0
    rng = np.random.default_rng(seed)
    ge = 0
    done = 0
    chunk = 1000
    while done < epochs:
        n = min(chunk, epochs - done)
        signs = rng.choice(np.array([-1.0, 1.0]), size=(n, len(v)))
        stats = np.median(signs * v, axis=1)
        ge += int(np.sum(stats >= observed - 1e-15))
        done += n
    return float((ge + 1) / (epochs + 1))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_archive(path: Path, meta: dict) -> dict:
    actual_size = path.stat().st_size
    actual_sha = sha256_file(path)
    expected_size = int(meta["size_bytes"])
    expected_sha = str(meta["lfs_sha256"]).lower()
    if actual_size != expected_size:
        raise SystemExit(f"archive size mismatch for {path.name}: {actual_size} != {expected_size}")
    if actual_sha.lower() != expected_sha:
        raise SystemExit(f"archive sha256 mismatch for {path.name}: {actual_sha} != {expected_sha}")
    return {"path": str(path), "size_bytes": actual_size, "sha256": actual_sha, "verified": True}


def _data_member(zf: zipfile.ZipFile) -> str:
    files = [
        n for n in zf.namelist()
        if not n.endswith("/") and "__macosx/" not in n.lower()
    ]
    csv_members = [n for n in files if n.lower().endswith(".csv")]
    if len(csv_members) == 1:
        return csv_members[0]
    if len(csv_members) > 1:
        raise ValueError(f"expected exactly one HistData CSV member, found {csv_members}")
    txt_members = [n for n in files if n.lower().endswith(".txt")]
    if len(txt_members) == 1:
        return txt_members[0]
    raise ValueError(f"expected one HistData CSV member, or one TXT fallback, found {files}")


def load_histdata_zip(path: Path) -> tuple[pd.DataFrame, dict]:
    with zipfile.ZipFile(path) as zf:
        member = _data_member(zf)
        raw = zf.read(member)

    d = pd.read_csv(
        BytesIO(raw),
        sep=";",
        header=None,
        names=["timestamp", "open", "high", "low", "close", "volume"],
        dtype=str,
        engine="python",
    )
    if d.shape[1] != 6:
        raise ValueError(f"unexpected HistData column count: {d.shape[1]}")

    parsed = pd.to_datetime(d["timestamp"].str.strip(), format="%Y%m%d %H%M%S", errors="coerce")
    bad_time = int(parsed.isna().sum())
    if bad_time:
        raise ValueError(f"{bad_time} HistData timestamps failed strict YYYYMMDD HHMMSS parse")

    d["time"] = parsed.dt.tz_localize(FIXED_EST).dt.tz_convert("UTC")
    for c in ("open", "high", "low", "close", "volume"):
        d[c] = pd.to_numeric(d[c], errors="coerce")

    before = len(d)
    d = d.dropna(subset=["time", "open", "high", "low", "close"])
    d = d[(d[["open", "high", "low", "close"]] > 0).all(axis=1)]
    d = d[
        (d.high >= d[["open", "close"]].max(axis=1))
        & (d.low <= d[["open", "close"]].min(axis=1))
        & (d.high >= d.low)
    ]
    d = d.drop_duplicates("time", keep="last").sort_values("time").set_index("time")
    return d, {
        "archive": str(path),
        "member": member,
        "raw_rows": int(before),
        "valid_rows": int(len(d)),
        "first_utc": d.index.min() if len(d) else None,
        "last_utc": d.index.max() if len(d) else None,
    }


def exact_window(d: pd.DataFrame, start: pd.Timestamp, periods: int) -> pd.DataFrame | None:
    idx = pd.date_range(start, periods=periods, freq="1min", tz="UTC")
    x = d.reindex(idx)
    if x[["open", "high", "low", "close"]].isna().any().any():
        return None
    return x


def realized_vol(prices: np.ndarray) -> float:
    p = np.asarray(prices, dtype=float)
    if len(p) < 2 or np.any(~np.isfinite(p)) or np.any(p <= 0):
        return float("nan")
    r = np.diff(np.log(p))
    rv2 = float(np.sum(r * r))
    if not np.isfinite(rv2) or rv2 <= 0:
        return float("nan")
    return float(np.sqrt(rv2))


def raw_observation(d: pd.DataFrame, t0: pd.Timestamp) -> dict | None:
    pre = exact_window(d, t0 - pd.Timedelta(minutes=60), 60)
    fut = exact_window(d, t0, 60)
    pre_prices = exact_window(d, t0 - pd.Timedelta(minutes=61), 61)
    if pre is None or fut is None or pre_prices is None:
        return None
    pre_rv = realized_vol(pre_prices.close.to_numpy(float))
    future_prices = np.concatenate([[float(pre.close.iloc[-1])], fut.close.to_numpy(float)])
    future_rv = realized_vol(future_prices)
    future_range = float(fut.high.max() - fut.low.min())
    if not np.isfinite(pre_rv) or not np.isfinite(future_rv) or future_range <= 0:
        return None
    local = t0.tz_convert(NY)
    return {
        "t0_utc": t0,
        "ny_date": str(local.date()),
        "anchor_hour": int(local.hour),
        "pre_rv": pre_rv,
        "future_rv": future_rv,
        "future_range": future_range,
    }


def build_observations(d: pd.DataFrame, cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    grid = cfg["observation_grid"]
    src = cfg["source"]
    hours = set(int(x) for x in grid["anchor_hours_local"])
    local_idx = d.index.tz_convert(NY)
    warmup_start = pd.Timestamp(src["scorer_warmup_start_ny"], tz=NY)
    replication_end = pd.Timestamp(src["replication_end_exclusive_ny"], tz=NY)
    mask = (
        (local_idx >= warmup_start)
        & (local_idx < replication_end)
        & (local_idx.weekday < 5)
        & (local_idx.minute == int(grid["anchor_minute"]))
        & (local_idx.second == 0)
        & np.isin(local_idx.hour, list(hours))
    )
    anchors = d.index[mask]
    rows = []
    for t0 in anchors:
        obs = raw_observation(d, pd.Timestamp(t0))
        if obs is not None:
            rows.append(obs)
    raw = pd.DataFrame(rows)
    if raw.empty:
        raise ValueError("no valid HistData anchor observations")
    raw = raw.sort_values(["anchor_hour", "t0_utc"]).reset_index(drop=True)

    lookback = int(grid["same_clock_baseline_lookback_observations"])
    for source, dest in (
        ("pre_rv", "baseline_pre_rv"),
        ("future_rv", "baseline_future_rv"),
        ("future_range", "baseline_future_range"),
    ):
        raw[dest] = raw.groupby("anchor_hour", group_keys=False)[source].transform(
            lambda s: s.shift(1).rolling(lookback, min_periods=lookback).median()
        )

    raw["pre_rv_ratio"] = raw.pre_rv / raw.baseline_pre_rv
    raw["future_rv_ratio"] = raw.future_rv / raw.baseline_future_rv
    raw["future_range_ratio"] = raw.future_range / raw.baseline_future_range
    raw = raw.replace([np.inf, -np.inf], np.nan)

    replication_start = pd.Timestamp(src["replication_start_ny"], tz=NY)
    score_mask = raw["t0_utc"].map(lambda x: pd.Timestamp(x).tz_convert(NY) >= replication_start)
    scored = raw.loc[score_mask].copy()
    scored = scored.dropna(subset=["pre_rv_ratio", "future_rv_ratio", "future_range_ratio"])
    scored = scored[
        (scored.pre_rv_ratio > 0)
        & (scored.future_rv_ratio > 0)
        & (scored.future_range_ratio > 0)
    ]
    if scored.empty:
        raise ValueError("no HistData observations after causal same-clock warmup")
    return raw.sort_values("t0_utc").reset_index(drop=True), scored.sort_values("t0_utc").reset_index(drop=True)


def daily_effects(obs: pd.DataFrame, target: str, min_anchors: int) -> pd.DataFrame:
    rows = []
    for day, g in obs.groupby("ny_date", sort=True):
        q = g.dropna(subset=["pre_rv_ratio", target])
        if len(q) < min_anchors:
            continue
        eff = spearman(q.pre_rv_ratio.to_numpy(float), q[target].to_numpy(float))
        if np.isfinite(eff):
            rows.append({"ny_date": day, "n": int(len(q)), "effect": float(eff)})
    return pd.DataFrame(rows)


def anchor_effects(obs: pd.DataFrame, min_n: int) -> list[dict]:
    rows = []
    for hour, g in obs.groupby("anchor_hour", sort=True):
        q = g.dropna(subset=["pre_rv_ratio", "future_rv_ratio"])
        eff = spearman(q.pre_rv_ratio.to_numpy(float), q.future_rv_ratio.to_numpy(float)) if len(q) >= min_n else np.nan
        rows.append({"anchor_hour": int(hour), "n": int(len(q)), "effect": eff, "eligible": bool(len(q) >= min_n)})
    return rows


def data_quality_diagnostics(d: pd.DataFrame, daily: pd.DataFrame) -> dict:
    work = d[["close"]].copy()
    work["prev_time"] = work.index.to_series().shift(1)
    work["prev_close"] = work.close.shift(1)
    one_minute = (work.index.to_series() - work.prev_time) == pd.Timedelta(minutes=1)
    work["abs_log_return"] = np.where(
        one_minute & (work.prev_close > 0) & (work.close > 0),
        np.abs(np.log(work.close / work.prev_close)),
        np.nan,
    )
    top = work.dropna(subset=["abs_log_return"]).nlargest(5, "abs_log_return")
    daily_map = daily.set_index("ny_date")["effect"].to_dict() if len(daily) else {}
    rows = []
    for ts, r in top.iterrows():
        ny_date = str(pd.Timestamp(ts).tz_convert(NY).date())
        rows.append({
            "timestamp_utc": pd.Timestamp(ts),
            "ny_date": ny_date,
            "abs_log_return": float(r.abs_log_return),
            "daily_primary_effect_if_scorable": daily_map.get(ny_date),
        })
    return {
        "max_abs_one_minute_log_return": float(top.abs_log_return.max()) if len(top) else np.nan,
        "top_five": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--zip2022", required=True)
    ap.add_argument("--zip2023", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--daily-output")
    ap.add_argument("--anchor-output")
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    if cfg.get("protocol_status") != "independent_source_replication_frozen":
        raise SystemExit("replication protocol is not frozen")
    if cfg.get("economic_scoring_enabled") is not False:
        raise SystemExit("economics must remain disabled")
    if cfg["parent_candidate"]["candidate_id"] != "rv_persistence":
        raise SystemExit("unexpected parent candidate")
    if cfg["parent_candidate"]["frozen_sign"] != "positive":
        raise SystemExit("unexpected frozen sign")
    if cfg["replication_classification"]["instrument_independent"] is not False:
        raise SystemExit("HistData replication must remain same-instrument")

    z22 = Path(args.zip2022)
    z23 = Path(args.zip2023)
    v22 = verify_archive(z22, cfg["source"]["warmup_archive"])
    v23 = verify_archive(z23, cfg["source"]["replication_archive"])
    d22, q22 = load_histdata_zip(z22)
    d23, q23 = load_histdata_zip(z23)
    d = pd.concat([d22, d23], axis=0).sort_index()
    d = d[~d.index.duplicated(keep="last")]

    years = set(int(y) for y in d.index.year.unique())
    if not years.issubset({2022, 2023}) or 2023 not in years:
        raise SystemExit(f"unexpected source years: {sorted(years)}")

    raw, obs = build_observations(d, cfg)
    score_local = obs.t0_utc.map(lambda x: pd.Timestamp(x).tz_convert(NY))
    if not all(ts.year == 2023 for ts in score_local):
        raise SystemExit("non-2023 anchor entered replication inference")

    min_anchors = int(cfg["observation_grid"]["minimum_daily_anchor_count_for_inference"])
    daily = daily_effects(obs, "future_rv_ratio", min_anchors)
    secondary = daily_effects(obs, "future_range_ratio", min_anchors)
    if daily.empty:
        raise SystemExit("no scorable HistData replication dates")

    effects = daily.effect.to_numpy(float)
    primary_effect = float(np.median(effects))
    positive_fraction = float(np.mean(effects > 0))
    p = positive_signflip_p(
        effects,
        int(cfg["statistics"]["permutation_epochs"]),
        stable_seed(cfg["statistics"]["random_seed_namespace"], cfg["parent_candidate"]["candidate_id"]),
    )
    secondary_effects = secondary.effect.to_numpy(float) if len(secondary) else np.array([], dtype=float)
    secondary_median = float(np.median(secondary_effects)) if len(secondary_effects) else np.nan

    dates = pd.to_datetime(daily.ny_date)
    first = daily.loc[dates < pd.Timestamp("2023-07-01"), "effect"].to_numpy(float)
    second = daily.loc[dates >= pd.Timestamp("2023-07-01"), "effect"].to_numpy(float)
    first_median = float(np.median(first)) if len(first) else np.nan
    second_median = float(np.median(second)) if len(second) else np.nan

    anchor_rows = anchor_effects(obs, int(cfg["replication_gate"]["minimum_anchor_slot_observations"]))
    positive_anchor_slots = sum(1 for r in anchor_rows if r["eligible"] and np.isfinite(r["effect"]) and r["effect"] > 0)
    gate = cfg["replication_gate"]
    gate_results = {
        "minimum_scorable_dates": len(daily) >= int(gate["minimum_scorable_dates"]),
        "minimum_median_daily_effect": primary_effect >= float(gate["minimum_median_daily_effect"]),
        "minimum_daily_positive_fraction": positive_fraction >= float(gate["minimum_daily_positive_fraction"]),
        "minimum_positive_anchor_slots": positive_anchor_slots >= int(gate["minimum_positive_anchor_slots"]),
        "first_half_positive": np.isfinite(first_median) and first_median > 0,
        "second_half_positive": np.isfinite(second_median) and second_median > 0,
        "secondary_range_positive": np.isfinite(secondary_median) and secondary_median > 0,
        "primary_p_max": p <= float(gate["primary_p_max"]),
    }
    passed = bool(all(gate_results.values()))

    output = {
        "protocol_id": cfg["protocol_id"],
        "stage": "independent_source_same_instrument_state_replication",
        "candidate_id": cfg["parent_candidate"]["candidate_id"],
        "candidate_sign": cfg["parent_candidate"]["frozen_sign"],
        "replication_classification": cfg["replication_classification"],
        "economic_scoring_run": False,
        "directional_scoring_run": False,
        "future_oos_claim": False,
        "source_verification": {"2022": v22, "2023": v23, "2022_parse": q22, "2023_parse": q23},
        "combined_input_rows": int(len(d)),
        "combined_input_start": d.index.min().isoformat(),
        "combined_input_end": d.index.max().isoformat(),
        "raw_anchor_observations_including_warmup": int(len(raw)),
        "replication_observations": int(len(obs)),
        "first_scorable_anchor_utc": obs.t0_utc.min(),
        "last_scorable_anchor_utc": obs.t0_utc.max(),
        "scorable_dates": int(len(daily)),
        "primary_median_daily_spearman": primary_effect,
        "daily_positive_fraction": positive_fraction,
        "one_sided_positive_signflip_p": p,
        "first_half_dates": int(len(first)),
        "first_half_median_daily_spearman": first_median,
        "second_half_dates": int(len(second)),
        "second_half_median_daily_spearman": second_median,
        "secondary_range_median_daily_spearman": secondary_median,
        "anchor_effects": anchor_rows,
        "positive_anchor_slots": int(positive_anchor_slots),
        "gate_results": gate_results,
        "replication_pass": passed,
        "data_quality_diagnostics": data_quality_diagnostics(d, daily),
        "claim_boundary": {
            "independent_source_robustness_only": True,
            "future_oos": False,
            "directional_edge": False,
            "economic_edge": False,
            "leverage_authorized": False,
            "live_enabled": False
        }
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(clean(output), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.daily_output:
        pth = Path(args.daily_output)
        pth.parent.mkdir(parents=True, exist_ok=True)
        daily.to_csv(pth, index=False)
    if args.anchor_output:
        pth = Path(args.anchor_output)
        pth.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(anchor_rows).to_csv(pth, index=False)
    print(json.dumps(clean(output), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
