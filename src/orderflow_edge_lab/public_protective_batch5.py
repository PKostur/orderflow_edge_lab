"""Frozen PSR11 hypothetical protective screen. Offline; no exchange/order clients."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
import hashlib
import io
import itertools
import json
from pathlib import Path
import platform
import subprocess
import sys
import zipfile
from copy import deepcopy

import numpy as np
import pandas as pd

from .protective_minute import Bracket, Minute, fixed_risk_quantity, resolve_minute, settle_buy, liquidation_cash
from .public_strategy_completion import clock_counts

DESIGN_COMMIT = "d586630a0ec845c5977976340d000f24a894b4af"
DESIGN_SHA256 = "5bc4de953e87850af00ac391f419798acb8ff137e4e4be30ec02663284595fbb"
CANDIDATES = ("MAGenSpot8hNativeKernel", "IchimokuSpot8hATR")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def epoch(text: str) -> int:
    return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())


def stamp(value: int) -> str:
    return datetime.fromtimestamp(int(value), timezone.utc).isoformat().replace("+00:00", "Z")


def checked_spec(root: Path, path: Path) -> dict:
    spec = json.loads(path.read_text())
    if digest(spec) != DESIGN_SHA256:
        raise ValueError("changed frozen design")
    frozen = json.loads(subprocess.check_output(["git", "show", f"{DESIGN_COMMIT}:{path.relative_to(root).as_posix()}"], cwd=root))
    if frozen != spec:
        raise ValueError("design is not the registered pre-outcome commit")
    for key, expected in (("source_manifest", "source_manifest_sha256"), ("quality_csv", "quality_csv_sha256")):
        if sha(root / spec[key]) != spec[expected]:
            raise ValueError("changed prior data provenance")
    return spec


def native_kernel(runtime: Path, wheel: Path, spec: dict):
    identity = spec["native"]
    if (platform.python_version() != identity["python"] or np.__version__ != identity["numpy"]
            or sys.platform != identity["platform"] or wheel.name != identity["wheel"]
            or sha(wheel) != identity["wheel_sha256"]):
        raise ValueError("native runtime differs from freeze")
    runtime = runtime.resolve()
    with zipfile.ZipFile(wheel) as archive:
        for name in ("jesse_rust/__init__.py", "jesse_rust/jesse_rust.cp313-win_amd64.pyd"):
            if (runtime / name).read_bytes() != archive.read(name):
                raise ValueError("installed kernel differs from pinned wheel")
    sys.path.insert(0, str(runtime))
    import jesse_rust
    if Path(jesse_rust.__file__).resolve().parent != runtime / "jesse_rust":
        raise ValueError("wrong native import")
    return jesse_rust


def retained_panel(root: Path, raw: Path, cache: Path, spec: dict) -> tuple[dict[str, np.ndarray], dict]:
    """Read only pinned complete archives; optional cache binds exact raw versions."""
    cache.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((root / spec["source_manifest"]).read_text())
    start, stop = epoch(spec["data_start"]), epoch(spec["data_end_exclusive"])
    grid = np.arange(start, stop, 60, dtype=np.int64)
    panel, evidence = {}, {}
    for symbol in [spec["benchmark"], *spec["symbols"]]:
        records = sorted([r for r in manifest if r["symbol"] == symbol and spec["data_start"][:7] <= r["month"] < spec["data_end_exclusive"][:7]], key=lambda r: r["month"])
        if len(records) != 42:
            raise ValueError("unexpected source-month coverage")
        fingerprints = []
        for r in records:
            if not r.get("checksum_verified") or not r.get("complete_month") or r.get("status") == "SOURCE_SCHEMA_REJECTED":
                raise ValueError("ineligible retained month")
            for relative_key, hash_key in (("raw_relative_path", "sha256"), ("checksum_relative_path", "checksum_sha256"),
                                           ("receipt_relative_path", "receipt_sha256"), ("checksum_receipt_relative_path", "checksum_receipt_sha256")):
                if sha(raw / r[relative_key]) != r[hash_key]:
                    raise ValueError("retained raw/checksum/receipt version changed")
            fingerprints.append({"month": r["month"], "raw_sha256": r["sha256"], "checksum_sha256": r["checksum_sha256"],
                                 "receipt_sha256": r["receipt_sha256"], "checksum_receipt_sha256": r["checksum_receipt_sha256"]})
        key = digest(fingerprints)
        data_path = cache / f"{symbol}-{key[:16]}.npy"
        receipt = data_path.with_suffix(".json")
        if data_path.exists() or receipt.exists():
            saved = json.loads(receipt.read_text())
            if saved["source_version_digest"] != key or saved["data_sha256"] != sha(data_path):
                raise ValueError("changed/unreceipted cache")
            values = np.load(data_path, allow_pickle=False)
        else:
            arrays = []
            for r in records:
                with zipfile.ZipFile(raw / r["raw_relative_path"]) as archive:
                    member = f"{symbol}-1m-{r['month']}.csv"
                    if archive.namelist() != [member]:
                        raise ValueError("unexpected CSV member")
                    frame = pd.read_csv(io.BytesIO(archive.read(member)), header=None, usecols=[0, 1, 2, 3, 4, 5, 6],
                                        dtype={0: "int64", 6: "int64"})
                unit = 1_000_000 if r["month"] >= "2025-01" else 1000
                opened, closed = frame[0].to_numpy(), frame[6].to_numpy()
                if np.any(opened % (60 * unit)) or np.any(closed != opened + 60 * unit - 1):
                    raise ValueError("changed minute alignment")
                arrays.append(np.column_stack([opened // unit, frame[[1, 2, 3, 4, 5]].to_numpy(dtype=np.float64)]))
            values = np.concatenate(arrays)
            np.save(data_path, values, allow_pickle=False)
            receipt.write_text(json.dumps({"source_version_digest": key, "data_sha256": sha(data_path)}, indent=2) + "\n")
        if (values.shape != (len(grid), 6) or not np.array_equal(values[:, 0], grid)
                or not np.isfinite(values).all() or np.any(values[:, 1:5] <= 0) or np.any(values[:, 5] < 0)
                or np.any(values[:, 2] < np.maximum(values[:, 1], values[:, 4]))
                or np.any(values[:, 3] > np.minimum(values[:, 1], values[:, 4]))):
            raise ValueError("incomplete/invalid minute panel")
        panel[symbol] = values
        evidence[symbol] = {"minutes": len(values), "start": stamp(start), "end_exclusive": stamp(stop),
                            "source_version_digest": key, "cache_data_sha256": sha(data_path), "archives": fingerprints}
    return panel, evidence


def bars8h(minutes: np.ndarray) -> np.ndarray:
    if len(minutes) % 480 or np.any(np.diff(minutes[:, 0]) != 60) or int(minutes[0, 0]) % 28800:
        raise ValueError("aligned complete 8h intervals required")
    blocks = minutes.reshape(-1, 480, 6)
    return np.column_stack([blocks[:, 0, 0] * 1000, blocks[:, 0, 1], blocks[:, -1, 4],
                            blocks[:, :, 2].max(axis=1), blocks[:, :, 3].min(axis=1), blocks[:, :, 5].sum(axis=1)])


def source_features(candles: np.ndarray, candidate: str, spec: dict, native=None) -> dict:
    n = len(candles)
    close = np.ascontiguousarray(candles[:, 2], dtype=np.float64)
    if candidate == CANDIDATES[0]:
        if native is None:
            raise ValueError("actual pinned kernel required")
        p = spec["magen"]
        fast, slow = native.linearreg(close, p["fast"]), native.linearreg(close, p["slow"])
        adx, atr = np.full(n, np.nan), np.full(n, np.nan)
        for i in range(n):
            window = np.ascontiguousarray(candles[max(0, i + 1 - p["native_nonsequential_window"]):i + 1])
            if len(window) > 2 * p["adx_period"]:
                adx[i] = native.adx(window, p["adx_period"])[-1]
            if len(window) >= p["atr_period"]:
                atr[i] = native.atr_last(window, p["atr_period"])
        prior_fast, prior_slow = np.r_[np.nan, fast[:-1]], np.r_[np.nan, slow[:-1]]
        return {"long": (fast > slow) & (prior_fast <= prior_slow) & (adx > p["adx_entry"]),
                "short": (fast < slow) & (prior_fast >= prior_slow) & (adx > p["adx_entry"]),
                "exit": (fast < slow) & (adx < p["adx_exit"]), "atr": atr,
                "stop_atr": p["stop_atr"], "target_atr": p["target_atr"], "risk_fraction": p["risk_fraction"]}
    if candidate != CANDIDATES[1]:
        raise ValueError("unregistered candidate")
    p = spec["ichimoku"]
    mids = {}
    for key in ("tenkan", "kijun", "span_b"):
        period = p[key]
        mids[key] = np.array([(max(candles[max(0, i - period + 1):i + 1, 3])
                                + min(candles[max(0, i - period + 1):i + 1, 4])) / 2 for i in range(n)])
    span_a = (mids["tenkan"] + mids["kijun"]) / 2
    long = (close > span_a) & (close > mids["span_b"]) & (mids["tenkan"] > mids["kijun"])
    short = (close < span_a) & (close < mids["span_b"]) & (mids["tenkan"] < mids["kijun"])
    tr = np.maximum(candles[:, 3] - candles[:, 4], np.maximum(abs(candles[:, 3] - np.r_[close[0], close[:-1]]),
                                                           abs(candles[:, 4] - np.r_[close[0], close[:-1]])))
    atr = np.full(n, np.nan)
    if n >= p["atr_period"]:
        j = p["atr_period"] - 1
        atr[j] = np.mean(tr[:j + 1])
        for i in range(j + 1, n):
            atr[i] = atr[i - 1] + (tr[i] - atr[i - 1]) / p["atr_period"]
    return {"long": long, "short": short, "exit": short, "atr": atr, "stop_atr": p["stop_atr"],
            "target_atr": p["target_atr"], "risk_fraction": None}


def net_bps(entry: float, endpoint: float, side: float) -> float:
    return 10000 * ((endpoint / entry) * (1 - side) / (1 + side) - 1)


def minute(row) -> Minute:
    return Minute(int(row[0]), float(row[1]), float(row[2]), float(row[3]), float(row[4]))


def event_record(position: dict, data: np.ndarray, btc: np.ndarray, j: int, price: float, side: float,
                 reason: str, at_open: bool, *, censored: bool = False) -> dict:
    first = position["entry_index"]
    prefix = data[first:j]
    known_high = max(position["entry_price"], float(data[j, 1]), price, float(prefix[:, 2].max()) if len(prefix) else price)
    known_low = min(position["entry_price"], float(data[j, 1]), price, float(prefix[:, 3].min()) if len(prefix) else price)
    possible_high = known_high if at_open else max(known_high, float(data[j, 2]))
    possible_low = known_low if at_open else min(known_low, float(data[j, 3]))
    if censored:
        known_high, known_low = possible_high, possible_low
        btc_low = btc_high = float(btc[j, 4])
    elif at_open:
        btc_low = btc_high = float(btc[j, 1])
    else:
        btc_low, btc_high = float(btc[j, 3]), float(btc[j, 2])
    net = net_bps(position["entry_price"], price, side)
    btc_lower, btc_upper = net_bps(position["btc_entry"], btc_low, side), net_bps(position["btc_entry"], btc_high, side)
    return {"status": "CENSORED_MTM" if censored else "COMPLETED", "entry_time": stamp(int(data[first, 0])),
            "signal_time": position["signal_time"], "entry_index": first, "endpoint_minute_index": j,
            "exit_interval": None if censored else [stamp(int(data[j, 0])), stamp(int(data[j, 0]) + (0 if at_open else 60))],
            "marked_at": stamp(int(data[j, 0]) + 60) if censored else None, "entry_price": position["entry_price"],
            "endpoint_reference_price": price, "quantity": position["quantity"], "reason": reason,
            "gross_bps": 10000 * (price / position["entry_price"] - 1), "net_bps": net,
            "btc_net_lower_bps": btc_lower, "btc_net_upper_bps": btc_upper,
            "excess_lower_bps": net - btc_upper, "excess_upper_bps": net - btc_lower,
            "mfe_bps_bounds": [10000 * (known_high / position["entry_price"] - 1), 10000 * (possible_high / position["entry_price"] - 1)],
            "mae_bps_bounds": [10000 * (possible_low / position["entry_price"] - 1), 10000 * (known_low / position["entry_price"] - 1)],
            "holding_minutes_to_endpoint": j - first + 1 if censored else (j - first if at_open else None),
            "holding_minutes_bounds": [j - first + 1, j - first + 1] if censored else [j - first, j - first + (0 if at_open else 1)],
            "purchase_cash": position["quantity"] * position["entry_price"] * (1 + side),
            "net_cash_profit_or_cutoff_mark": position["quantity"] * (price * (1 - side) - position["entry_price"] * (1 + side)),
            "initial_stop": position["initial_stop"],
            "initial_target": position["initial_target"], "last_stop": position["stop"], "last_target": position["target"]}


def settle_position(state: dict, data, btc, j: int, price: float, side: float, reason: str, at_open: bool) -> None:
    p = state["position"]
    state["events"].append(event_record(p, data, btc, j, price, side, reason, at_open))
    state["cash"] = liquidation_cash(state["cash"], p["quantity"], price, side_bps=side * 10000)
    lower, upper = (float(btc[j, 1]), float(btc[j, 1])) if at_open else (float(btc[j, 3]), float(btc[j, 2]))
    state["btc_cash_lower"] += p["btc_quantity_lower"] * lower * (1 - side)
    state["btc_cash_upper"] += p["btc_quantity_upper"] * upper * (1 - side)
    state["position"] = None


def mark(state: dict, alt_price: float, btc_price: float, side: float) -> tuple[float, float, float]:
    p = state["position"]
    if p is None:
        return state["cash"], state["btc_cash_lower"], state["btc_cash_upper"]
    return (state["cash"] + p["quantity"] * alt_price * (1 - side),
            state["btc_cash_lower"] + p["btc_quantity_lower"] * btc_price * (1 - side),
            state["btc_cash_upper"] + p["btc_quantity_upper"] * btc_price * (1 - side))


def simulate(data, btc, candles, features: dict, candidate: str, spec: dict, cost: float, gap_model: str,
             *, entry_flags=None) -> list[dict]:
    """One symbol; propagate full stop/target histories. No fabricated final exit."""
    if cost not in (20, 40, 60, 80) or gap_model not in ("conservative_limit", "opening_price_improvement") or candidate not in CANDIDATES:
        raise ValueError("unregistered execution model")
    if (data.shape != btc.shape or data.ndim != 2 or data.shape[1] != 6
            or not np.array_equal(data[:, 0], btc[:, 0]) or not np.array_equal(bars8h(data), candles)):
        raise ValueError("unaligned data/BTC/candles")
    if any(len(features[k]) != len(candles) for k in ("long", "short", "exit", "atr")):
        raise ValueError("feature length mismatch")
    if entry_flags is not None and len(entry_flags) != len(candles):
        raise ValueError("control flag length mismatch")
    side = cost / 20000
    flags = features["long"] if entry_flags is None else entry_flags
    initial = spec["episode_initial_cash_per_symbol"]
    states = [{"cash": float(initial), "btc_cash_lower": float(initial), "btc_cash_upper": float(initial),
               "position": None, "events": [], "counts": Counter(), "nav": [float(initial)],
               "btc_nav_lower": [float(initial)], "btc_nav_upper": [float(initial)]}]
    for b in range(spec["warmup_bars"], len(candles)):
        i, start, end = b - 1, b * 480, (b + 1) * 480
        next_states = []
        for state in states:
            p = state["position"]
            had_position = p is not None
            if flags[i]:
                state["counts"]["raw_entry_flags"] += 1
            if p is not None and flags[i]:
                state["counts"]["held_entry_ignored"] += 1
            if p is not None and features["exit"][i]:
                settle_position(state, data, btc, start, float(data[start, 1]), side, "source_signal_exit", True)
                p = None
            elif p is not None and candidate == CANDIDATES[1] and features["long"][i]:
                new_stop = float(candles[i, 2] - features["stop_atr"] * features["atr"][i])
                new_target = float(candles[i, 2] + features["target_atr"] * features["atr"][i])
                if not 0 < new_stop < new_target or not np.isfinite([new_stop, new_target]).all():
                    raise ValueError("invalid source bracket replacement")
                p.update(stop=new_stop, target=new_target, decided_at=int(data[start, 0]))
                state["counts"]["bracket_replacements"] += 1
            if p is None and not had_position and flags[i]:
                signal_price, atr = float(candles[i, 2]), float(features["atr"][i])
                stop, target = signal_price - features["stop_atr"] * atr, signal_price + features["target_atr"] * atr
                if not np.isfinite([stop, target, atr]).all() or not 0 < stop < target or atr <= 0:
                    state["counts"]["invalid_entry"] += 1
                else:
                    risk = features["risk_fraction"]
                    qty = fixed_risk_quantity(state["cash"], signal_price, stop, risk_fraction=risk if risk is not None else 1,
                                              reserve_side_bps=side * 10000)
                    buy = settle_buy(state["cash"], qty, float(data[start, 1]), side_bps=side * 10000)
                    if not buy.accepted:
                        state["counts"]["cash_rejected" if buy.reason == "insufficient_cash" else "zero_quantity"] += 1
                    else:
                        fraction = qty * buy.reference_price / state["cash"]
                        qlo = state["btc_cash_lower"] * fraction / float(btc[start, 1])
                        qhi = state["btc_cash_upper"] * fraction / float(btc[start, 1])
                        state["btc_cash_lower"] -= qlo * float(btc[start, 1]) * (1 + side)
                        state["btc_cash_upper"] -= qhi * float(btc[start, 1]) * (1 + side)
                        if min(state["btc_cash_lower"], state["btc_cash_upper"]) < -1e-8:
                            raise ValueError("unfunded benchmark")
                        state["btc_cash_lower"] = max(0, state["btc_cash_lower"])
                        state["btc_cash_upper"] = max(0, state["btc_cash_upper"])
                        state["cash"] = buy.remaining_cash
                        p = {"entry_index": start, "entry_price": buy.reference_price, "quantity": qty, "stop": stop, "target": target,
                             "initial_stop": stop, "initial_target": target, "btc_entry": float(btc[start, 1]),
                             "btc_quantity_lower": qlo, "btc_quantity_upper": qhi,
                             "signal_time": stamp(int(data[start, 0])), "decided_at": int(data[start, 0])}
                        state["position"] = p
                        state["counts"]["accepted_entries"] += 1
            if p is not None:
                window = data[start:end]
                touched = np.flatnonzero((window[:, 3] <= p["stop"]) | (window[:, 2] >= p["target"]))
                if len(touched):
                    j = start + int(touched[0])
                    bounds = resolve_minute(minute(data[j]), Bracket(p["stop"], p["target"], p["decided_at"], p["decided_at"]))
                    if bounds is None:
                        raise ValueError("touch scan/resolver disagreement")
                    if bounds.reason == "both_touched_order_unknown":
                        alternative = deepcopy(state)
                        settle_position(state, data, btc, j, bounds.lower_price, side, "both_touch_stop_first", False)
                        settle_position(alternative, data, btc, j, bounds.upper_price, side, "both_touch_target_first", False)
                        next_states.append(alternative)
                    else:
                        price = bounds.upper_price if bounds.reason == "target_gap" and gap_model == "opening_price_improvement" else bounds.lower_price
                        settle_position(state, data, btc, j, price, side, bounds.reason, bounds.at_open)
            next_states.append(state)
        states = next_states
        if len(states) > spec["max_symbol_histories"]:
            raise ValueError("HISTORY_LIMIT_EXCEEDED")
        for state in states:
            values = mark(state, float(data[end - 1, 4]), float(btc[end - 1, 4]), side)
            if not np.isfinite(values).all() or min(values) <= 0:
                raise ValueError("invalid portfolio wealth")
            state["nav"].append(values[0])
            state["btc_nav_lower"].append(values[1])
            state["btc_nav_upper"].append(values[2])
    for state in states:
        if flags[-1]:
            state["counts"]["raw_entry_flags"] += 1
            state["counts"]["held_entry_ignored" if state["position"] is not None else "unexecuted_final_entry"] += 1
        p = state["position"]
        if p is not None:
            state["events"].append(event_record(p, data, btc, len(data) - 1, float(data[-1, 4]), side, "fixed_cutoff_mark", False, censored=True))
            state["pending_source_exit"] = bool(features["exit"][-1])
            state["pending_bracket_update"] = bool(candidate == CANDIDATES[1] and features["long"][-1])
        account = state["counts"]
        if account["raw_entry_flags"] != sum(account[k] for k in ("held_entry_ignored", "invalid_entry", "cash_rejected", "zero_quantity", "accepted_entries", "unexecuted_final_entry")):
            raise ValueError("signal accounting failed")
        if account["accepted_entries"] != len(state["events"]):
            raise ValueError("completed/pending admission accounting failed")
        state["counts"] = dict(state["counts"])
    return states


def mean(values) -> float | None:
    return float(np.mean(values)) if len(values) else None


def pf(values) -> float | None:
    positive = sum(x for x in values if x > 0)
    negative = -sum(x for x in values if x < 0)
    return positive / negative if negative else None


def enrich(states: list[dict], symbol: str, btc_candles: np.ndarray) -> None:
    for state in states:
        for event in state["events"]:
            t = datetime.fromisoformat(event["entry_time"].replace("Z", "+00:00"))
            b = event["entry_index"] // 480
            prior = btc_candles[b - 30:b, 2]
            direction = float(btc_candles[b - 1, 2] / btc_candles[b - 31, 2] - 1)
            vol = float(np.std(np.diff(np.log(prior)), ddof=1))
            event.update(symbol=symbol, year=t.year, month=t.strftime("%Y-%m"), weekday=t.weekday(), utc_hour=t.hour,
                         entry_week=(t - timedelta(days=t.weekday())).date().isoformat(),
                         btc_direction="up" if direction > 0 else "down" if direction < 0 else "flat",
                         btc_volatility="high" if vol >= .025 else "low")


def summary(events: list[dict]) -> dict:
    completed = [e for e in events if e["status"] == "COMPLETED"]
    values = [e["net_bps"] for e in events]
    return {"admitted": len(events), "completed": len(completed), "censored_mtm": len(events) - len(completed),
            "mean_net_bps": mean(values), "median_net_bps": float(np.median(values)) if values else None,
            "mean_completed_only_net_bps": mean([e["net_bps"] for e in completed]),
            "per_unit_profit_factor": pf(values), "cash_profit_factor_with_cutoff_marks": pf([e["net_cash_profit_or_cutoff_mark"] for e in events]),
            "completed_cash_profit_factor": pf([e["net_cash_profit_or_cutoff_mark"] for e in completed]),
            "win_fraction": mean([int(e["net_bps"] > 0) for e in events]), "mean_gross_bps": mean([e["gross_bps"] for e in events]),
            "mean_btc_excess_lower_bps": mean([e["excess_lower_bps"] for e in events]),
            "mean_btc_excess_upper_bps": mean([e["excess_upper_bps"] for e in events]),
            "mean_mfe_lower_bps": mean([e["mfe_bps_bounds"][0] for e in events]),
            "mean_mfe_upper_bps": mean([e["mfe_bps_bounds"][1] for e in events]),
            "mean_mae_lower_bps": mean([e["mae_bps_bounds"][0] for e in events]),
            "mean_mae_upper_bps": mean([e["mae_bps_bounds"][1] for e in events])}


def joint_histories(by_symbol: dict[str, list[dict]], spec: dict):
    total = int(np.prod([len(v) for v in by_symbol.values()]))
    if total > spec["max_joint_histories"]:
        raise ValueError("JOINT_HISTORY_LIMIT_EXCEEDED")
    return itertools.product(*[by_symbol[s] for s in spec["symbols"]])


def portfolio(states: tuple) -> dict:
    nav = np.mean([s["nav"] for s in states], axis=0)
    lower = np.mean([s["btc_nav_lower"] for s in states], axis=0)
    upper = np.mean([s["btc_nav_upper"] for s in states], axis=0)
    peaks = np.maximum.accumulate(nav)
    return {"nav": nav.tolist(), "btc_nav_lower": lower.tolist(), "btc_nav_upper": upper.tolist(),
            "roi_pct": float(100 * (nav[-1] / nav[0] - 1)),
            "drawdown_pct": float(100 * np.min(nav / peaks - 1)),
            "funded_btc_roi_lower_pct": float(100 * (lower[-1] / lower[0] - 1)),
            "funded_btc_roi_upper_pct": float(100 * (upper[-1] / upper[0] - 1)),
            "note": "8h-close hypothetical liquidation-value marks; drawdown is not an intrabar bound. Funded BTC intervals are reference bounds, not executed fills."}


def calendar_weeks(spec: dict) -> list[str]:
    first = datetime.fromtimestamp(epoch(spec["data_start"]) + spec["warmup_bars"] * 28800, timezone.utc)
    first = (first - timedelta(days=first.weekday())).date()
    last = datetime.fromtimestamp(epoch(spec["data_end_exclusive"]) - 1, timezone.utc).date()
    result = []
    while first <= last:
        result.append(first.isoformat())
        first += timedelta(days=7)
    return result


def block_draws(spec: dict, seed: int) -> np.ndarray:
    n = len(calendar_weeks(spec))
    width = spec["bootstrap_calendar_block_weeks"]
    if n < width:
        raise ValueError("insufficient calendar for registered blocks")
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, n - width + 1, size=(spec["bootstrap_replicates"], (n + width - 1) // width))
    return (starts[:, :, None] + np.arange(width)).reshape(spec["bootstrap_replicates"], -1)[:, :n]


def event_diagnostics(events: list[dict], spec: dict, draws: np.ndarray) -> dict:
    groups = {}
    for key in ("symbol", "year", "month", "weekday", "utc_hour", "btc_direction", "btc_volatility"):
        grouped = defaultdict(list)
        for e in events:
            grouped[str(e[key])].append(e)
        groups[key] = {value: summary(items) for value, items in sorted(grouped.items())}
    weekly = defaultdict(list)
    for e in events:
        weekly[e["entry_week"]].append(e)
    weeks = calendar_weeks(spec)
    values = np.array([[sum(e["net_bps"] for e in weekly.get(w, [])), sum(e["excess_lower_bps"] for e in weekly.get(w, [])), len(weekly.get(w, []))] for w in weeks], dtype=float)
    resampled = values[draws].sum(axis=1)
    usable = resampled[:, 2] > 0
    alpha = .05 / len(CANDIDATES)
    ci = {}
    for key, column in (("net_bps", 0), ("excess_lower_bps", 1)):
        ci[key] = np.quantile(resampled[usable, column] / resampled[usable, 2], [alpha / 2, 1 - alpha / 2]).tolist() if usable.any() else [None, None]
    leave_week = {w: summary([e for e in events if e["entry_week"] != w]) for w in weekly}
    leave_symbol = {s: summary([e for e in events if e["symbol"] != s]) for s in spec["symbols"]}
    years = list(range(int(spec["data_start"][:4]), int(spec["data_end_exclusive"][:4]) + 1))
    positive_year_fraction = sum(groups["year"].get(str(y), {}).get("mean_net_bps", 0) > 0 for y in years) / len(years)
    times = [datetime.fromisoformat(e["entry_time"].replace("Z", "+00:00")) for e in events]
    return {"groups": groups, "entry_week_counts": {w: len(weekly.get(w, [])) for w in weeks}, "entry_weeks": len(weekly),
            "calendar_weeks_with_zeros": len(weeks), "bootstrap": {"descriptive_only": True, "replicates": spec["bootstrap_replicates"],
            "moving_calendar_block_weeks": spec["bootstrap_calendar_block_weeks"], "alpha_per_candidate": alpha,
            "two_sided_interval_coverage": 1 - alpha, "quantiles": [alpha / 2, 1 - alpha / 2],
            "defined_ratio_replicates": int(usable.sum()), "intervals": ci}, "leave_week": leave_week, "leave_symbol": leave_symbol,
            "worst_leave_week_mean_bps": min((v["mean_net_bps"] for v in leave_week.values() if v["mean_net_bps"] is not None), default=None),
            "positive_year_fraction": positive_year_fraction, "all_calendar_years_in_denominator": years,
            "entry_clock": clock_counts(times)}


def gate_checks(base: dict, stress_minimum: float | None, placebo_tail: float, spec: dict) -> dict:
    s, d, g = base["summary"], base["diagnostics"], spec["gates"]
    positive = lambda value: value is not None and value > 0
    lower = d["bootstrap"]["intervals"]
    return {"completed_events": s["completed"] >= g["min_completed_events"], "entry_weeks": d["entry_weeks"] >= g["min_entry_weeks"],
            "net40_mean": s["mean_net_bps"] is not None and s["mean_net_bps"] > g["min_all_admitted_net40_bps"],
            "net80_positive": positive(stress_minimum),
            "all_symbols_positive": all(positive(d["groups"]["symbol"].get(symbol, {}).get("mean_net_bps")) for symbol in spec["symbols"]),
            "positive_year_fraction": d["positive_year_fraction"] >= g["min_positive_year_fraction"],
            "portfolio_drawdown": -base["portfolio"]["drawdown_pct"] < g["max_portfolio_drawdown_pct"],
            "leave_week_positive": positive(d["worst_leave_week_mean_bps"]),
            "net_descriptive_ci": positive(lower["net_bps"][0]), "excess_descriptive_ci": positive(lower["excess_lower_bps"][0]),
            "placebo_tail": placebo_tail <= g["max_placebo_at_least_observed_fraction"], "no_history_overflow": True}


def randomized_flags(flags: np.ndarray, candles: np.ndarray, spec: dict, rng) -> np.ndarray:
    result = np.zeros(len(flags), dtype=bool)
    groups = defaultdict(list)
    for i in range(spec["warmup_bars"] - 1, len(flags)):
        t = datetime.fromtimestamp(int(candles[i, 0] // 1000) + 28800, timezone.utc)
        groups[(t - timedelta(days=t.weekday())).date().isoformat()].append(i)
    for indices in groups.values():
        count = int(np.sum(flags[indices]))
        if count:
            result[rng.choice(indices, size=count, replace=False)] = True
    return result


def _evaluate_candidate(candidate: str, panel: dict, frames: dict, features: dict, spec: dict, output_progress=print) -> dict:
    cases = {}
    draws = block_draws(spec, spec["seed"] + CANDIDATES.index(candidate))
    for cost in spec["cost_cases_bps"]:
        for gap in spec["gap_target_models"]:
            histories = {}
            for symbol in spec["symbols"]:
                states = simulate(panel[symbol], panel[spec["benchmark"]], frames[symbol], features[symbol], candidate, spec, cost, gap)
                enrich(states, symbol, frames[spec["benchmark"]])
                histories[symbol] = states
            joints = []
            for indexes, states in enumerate(joint_histories(histories, spec)):
                events = [e for state in states for e in state["events"]]
                joints.append({"joint_id": indexes, "summary": summary(events), "diagnostics": event_diagnostics(events, spec, draws), "portfolio": portfolio(states)})
            cases[f"{cost}:{gap}"] = {"symbols": histories, "joint_histories": joints}
            output_progress(json.dumps({"candidate": candidate, "cost": cost, "gap_model": gap, "joint_histories": len(joints),
                                        "admitted": joints[0]["summary"]["admitted"], "completed": joints[0]["summary"]["completed"]}), flush=True)
    originals = [joint for key, case in cases.items() if key.startswith("40:") for joint in case["joint_histories"]]
    observed_minimum = min((j["summary"]["mean_net_bps"] for j in originals if j["summary"]["mean_net_bps"] is not None), default=None)
    stress = [j["summary"]["mean_net_bps"] for key, case in cases.items() if key.startswith("80:") for j in case["joint_histories"]]
    stress_minimum = min(stress) if stress and all(value is not None for value in stress) else None
    rng = np.random.default_rng(spec["seed"] + 100 + CANDIDATES.index(candidate))
    control_means = []
    for repetition in range(spec["placebo_replicates"]):
        flags = {s: randomized_flags(features[s]["long"], frames[s], spec, rng) for s in spec["symbols"]}
        maxima = []
        for gap in spec["gap_target_models"]:
            histories = {}
            for symbol in spec["symbols"]:
                histories[symbol] = simulate(panel[symbol], panel[spec["benchmark"]], frames[symbol], features[symbol], candidate, spec, 40, gap, entry_flags=flags[symbol])
            for states in joint_histories(histories, spec):
                value = mean([e["net_bps"] for s in states for e in s["events"]])
                if value is not None:
                    maxima.append(value)
        control_means.append(max(maxima) if maxima else None)
        if (repetition + 1) % 50 == 0:
            output_progress(json.dumps({"candidate": candidate, "randomized_entry_controls_done": repetition + 1}), flush=True)
    tail = sum(x is None or observed_minimum is None or x >= observed_minimum for x in control_means) / len(control_means)
    lagged = {}
    for gap in spec["gap_target_models"]:
        histories = {}
        for symbol in spec["symbols"]:
            flags = np.zeros(len(frames[symbol]), dtype=bool)
            eligible = features[symbol]["long"].copy()
            eligible[:spec["warmup_bars"] - 1] = False
            flags[spec["lag_control_bars"]:] = eligible[:-spec["lag_control_bars"]]
            histories[symbol] = simulate(panel[symbol], panel[spec["benchmark"]], frames[symbol], features[symbol], candidate, spec, 40, gap, entry_flags=flags)
            enrich(histories[symbol], symbol, frames[spec["benchmark"]])
        lagged[gap] = [summary([e for s in states for e in s["events"]]) for states in joint_histories(histories, spec)]
    checks = [gate_checks(j, stress_minimum, tail, spec) for j in originals]
    failed = sorted({key for record in checks for key, passed in record.items() if not passed})
    return {"candidate": candidate, "decision": "REJECTED_AS_ADAPTED" if failed else "SCREEN_SURVIVOR_FOR_FUTURE_REGISTRATION",
            "failed_gates": failed, "gate_checks_all_baseline_joint_histories": checks, "cost_and_gap_cases": cases,
            "randomized_entry_control": {"replicates": len(control_means), "maximum_cohort_mean_per_rep": control_means,
                                         "original_minimum_cohort_mean": observed_minimum, "tail_fraction_at_least_observed": tail,
                                         "endogenous_durations_reused": False, "descriptive_only": True},
            "seven_bar_lag_control": lagged, "viable": False, "future_confirmation_started": False}


def evaluate_candidate(candidate: str, panel: dict, frames: dict, features: dict, spec: dict, output_progress=print) -> dict:
    try:
        return _evaluate_candidate(candidate, panel, frames, features, spec, output_progress)
    except ValueError as error:
        if "HISTORY_LIMIT_EXCEEDED" not in str(error):
            raise
        # Never prune ambiguous histories to manufacture a tractable survivor.
        return {"candidate": candidate, "decision": "REJECTED_AS_ADAPTED", "failed_gates": ["no_history_overflow"],
                "evaluation_complete": False, "error": str(error), "viable": False,
                "future_confirmation_started": False,
                "note": "Registered history limit reached in a baseline or control; exhaustive evaluation unavailable. No history pruning or rule change."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--config", type=Path, default=Path("config/public_protective_batch5_v1.json"))
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--native-runtime", type=Path, required=True)
    parser.add_argument("--native-wheel", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.output.exists():
        raise ValueError("retain previous attempts; choose a new output path")
    spec = checked_spec(root, (root / args.config).resolve())
    source_path = Path(__file__).resolve()
    committed_source = subprocess.check_output(["git", "show", f"HEAD:{source_path.relative_to(root).as_posix()}"], cwd=root)
    if committed_source.replace(b"\r\n", b"\n") != source_path.read_bytes().replace(b"\r\n", b"\n"):
        raise ValueError("commit the evaluator before inspecting market outcomes")
    native = native_kernel(args.native_runtime, args.native_wheel, spec)
    panel, source = retained_panel(root, args.raw, args.cache, spec)
    frames = {s: bars8h(data) for s, data in panel.items()}
    results = []
    for candidate in CANDIDATES:
        features = {s: source_features(frames[s], candidate, spec, native) for s in spec["symbols"]}
        results.append(evaluate_candidate(candidate, panel, frames, features, spec))
    report = {"study_id": spec["study_id"], "design_commit": DESIGN_COMMIT, "design_sha256": DESIGN_SHA256,
              "evaluator_git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
              "evaluator_source_sha256": sha(Path(__file__)), "runtime": {"python": platform.python_version(), "numpy": np.__version__,
              "pandas": pd.__version__, "native_wheel_sha256": sha(args.native_wheel)}, "source": source, "results": results,
              "claim": spec["claim"], "new_tested_trading_cells": 2, "minimum_cumulative_trading_cells": 17,
              "minimum_cumulative_signal_model_cells": 18, "viable_candidates": [], "orders": False,
              "frozen_lanes_modified": False, "future_untouched_confirmation_required": True}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "sha256": sha(args.output), "decisions": [(r["candidate"], r["decision"], r["failed_gates"]) for r in results]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
