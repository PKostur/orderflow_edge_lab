"""2021-2023 1m kline + funding loader for leverage-bracket-study-v2 (descriptive; no keys, no orders).

Spec: ``config/leverage_bracket_study_v2.json`` (frozen).  Same parsing / checksum rules as
``leverage_bracket_data`` (v1), but on the primary-sample grid and with disk safeguards:

* grid index ``i`` = bar END in minutes since ``GRID_START`` (2020-12-31 00:00 UTC, one day of warm-up);
  ``SAMPLE_START_IDX`` = 1440 (the bar ending 2021-01-01 00:00); ``GRID_END`` = 2024-01-01 00:00 (the bar ending then is
  the 2023-12-31 23:59 bar);
* arrays are stored ``(3, N)`` float32 ``[high, low, close]`` (NaN = no bar).  float32 has a relative rounding error of at most
  2**-24 = 6e-8, against the smallest level distance the study uses (0.01% through-fill = 1e-4 of price, take-profit
  1% of price at 10x), i.e. >1600x smaller; the OHLC validity and the stale-tail rule are evaluated on the float64 values
  before conversion and the effect of the conversion is recorded per symbol;
* every zip is deleted after parsing; free disk space is checked before every download and the run stops cleanly
  (``DiskSpaceLow``) when free space would fall below ``MIN_FREE_BYTES``.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import shutil
import threading
import time
from typing import Any

import numpy as np
import pandas as pd

from orderflow_edge_lab import binance_futures_archive as archive
from orderflow_edge_lab import leverage_bracket_data as bdata
from orderflow_edge_lab.binance_spot_archive import data_url, download_verified, list_all, safe_name

GRID_START = pd.Timestamp("2020-12-31", tz="UTC")
GRID_END = pd.Timestamp("2024-01-01", tz="UTC")
GRID_START_MIN = int(GRID_START.timestamp() // 60)
GRID_LEN = int((GRID_END - GRID_START) / pd.Timedelta(minutes=1)) + 1
SAMPLE_START = pd.Timestamp("2021-01-01", tz="UTC")
SAMPLE_START_IDX = int((SAMPLE_START - GRID_START) / pd.Timedelta(minutes=1))
MINUTES_PER_DAY = 1440
FIRST_MONTH = "2020-12"  # the monthly file that contains 2020-12-31
LAST_MONTH = "2023-12"
FUNDING_END = "2024-01-01"  # includes the settlement on the last grid bar (2024-01-01 00:00)
PRIMARY_DAYS = (GRID_LEN - 1 - SAMPLE_START_IDX) // MINUTES_PER_DAY  # 1095 (2021, 2022, 2023)
HALF_1_END = "2022-06-30"
MIN_FREE_BYTES = 1_000_000_000
SAFETY_BYTES = 300_000_000  # headroom for in-flight zips and the arrays being written
KLINE_1M = bdata.KLINE_1M
_COLUMNS = list(archive.KLINE_COLUMNS)
FLOAT32_EPS = float(np.finfo(np.float32).eps) / 2.0  # max relative rounding error 2**-24


class DiskSpaceLow(RuntimeError):
    """Free disk space would fall below the floor; the download stops cleanly."""


def free_bytes(path: Path) -> int:
    return int(shutil.disk_usage(path).free)


def check_free(path: Path, *, need: int = SAFETY_BYTES, floor: int = MIN_FREE_BYTES) -> int:
    """Raise ``DiskSpaceLow`` unless ``free - need >= floor``; returns the free bytes."""
    free = free_bytes(path)
    if free - need < floor:
        raise DiskSpaceLow(f"free space {free / 1e9:.2f} GB (+{need / 1e6:.0f} MB headroom) would fall below "
                           f"{floor / 1e9:.1f} GB")
    return free


def parse_minute_csv(raw: bytes | str) -> pd.DataFrame:
    """1m kline csv -> frame ``[open, high, low, close]`` indexed by the grid index of the bar END (v2 grid)."""
    frame = archive._read_rows(raw, _COLUMNS)
    if frame.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close"], dtype=float,
                            index=pd.Index([], dtype="int64"))
    seconds = archive._epoch_seconds(frame["open_time"].astype("int64").to_numpy())
    idx = seconds // 60 + 1 - GRID_START_MIN
    return pd.DataFrame({c: pd.to_numeric(frame[c]).to_numpy(dtype=float) for c in ("open", "high", "low", "close")},
                        index=pd.Index(idx.astype("int64")))


def parse_minute_zip(data: bytes) -> pd.DataFrame:
    return parse_minute_csv(archive._csv_member(data))


def to_grid(frame: pd.DataFrame) -> tuple[np.ndarray, dict[str, Any]]:
    """Frame -> ``(4, GRID_LEN)`` float64 array [open, high, low, close] and bar statistics (v2 grid)."""
    dups = int(frame.index.duplicated().sum())
    frame = frame[~frame.index.duplicated(keep="first")]
    inside = frame[(frame.index >= 0) & (frame.index < GRID_LEN)]
    grid = np.full((4, GRID_LEN), np.nan)
    pos = inside.index.to_numpy()
    for k, col in enumerate(("open", "high", "low", "close")):
        grid[k, pos] = inside[col].to_numpy()
    present = ~np.isnan(grid[3])
    stats: dict[str, Any] = {"bars": int(present.sum()), "duplicates_dropped": dups}
    if present.any():
        first, last = int(np.argmax(present)), int(len(present) - 1 - np.argmax(present[::-1]))
        span = present[first:last + 1]
        stats.update(first_bar_end=str(GRID_START + pd.Timedelta(minutes=first)),
                     last_bar_end=str(GRID_START + pd.Timedelta(minutes=last)),
                     missing_inside_span=int((~span).sum()))
        gaps = np.diff(np.flatnonzero(present[first:last + 1])) - 1
        gaps = gaps[gaps > 0]
        stats.update(gap_count=int(len(gaps)), longest_gap_minutes=int(gaps.max()) if len(gaps) else 0,
                     gaps_over_60m=int((gaps > 60).sum()))
    o, h, lo, c = grid
    with np.errstate(invalid="ignore"):
        bad = (h < np.fmax(o, c)) | (lo > np.fmin(o, c)) | (h < lo)
    stats["ohlc_violations"] = int(np.nansum(bad))
    return grid, stats


def float32_effect(hlc64: np.ndarray) -> dict[str, Any]:
    """Effect of storing ``[high, low, close]`` as float32 (data-quality only): the largest relative rounding error,
    bars whose high and low differ in float64 but coincide in float32, any high < low created, and whether the
    stale-tail start is unchanged."""
    hlc32 = hlc64.astype(np.float32)
    ok = ~np.isnan(hlc64[2])
    if not ok.any():
        return {"max_rel_error": 0.0, "range_collapsed_bars": 0, "high_below_low_after": 0, "stale_tail_unchanged": True}
    a, b = hlc64[:, ok], hlc32[:, ok].astype(np.float64)
    rel = float(np.max(np.abs(b - a) / np.abs(a)))
    collapsed = int(((a[0] != a[1]) & (b[0] == b[1])).sum())
    inverted = int((b[0] < b[1]).sum())
    t64 = bdata.stale_tail_start(hlc64[0], hlc64[1], hlc64[2])
    t32 = bdata.stale_tail_start(hlc32[0].astype(np.float64), hlc32[1].astype(np.float64), hlc32[2].astype(np.float64))
    return {"max_rel_error": rel, "range_collapsed_bars": collapsed, "high_below_low_after": inverted,
            "stale_tail_unchanged": t64 == t32}


def iter_kline_zips(symbol: str, directory: Path, *, fetch: Any = archive.http_fetch, free_check: Any = None):
    """Yield ``(file name, sha256, data)`` for the 1m zips of ``symbol`` (monthly where published, else daily); the
    zip (and its checksum file) is deleted right after the consumer has parsed it.  ``free_check`` is called before
    every download."""
    from hashlib import sha256
    monthly_prefix, daily_prefix = (p.format(s=symbol) for p in KLINE_1M)
    _, mkeys = list_all(monthly_prefix, fetch=fetch)
    monthly = {archive._month_of(k, "monthly"): k for k in mkeys if k.endswith(".zip")}
    daily_keys: list[str] | None = None
    for month in bdata.months_between(FIRST_MONTH, LAST_MONTH):
        keys = [monthly[month]] if month in monthly else None
        if keys is None:
            if daily_keys is None:
                _, daily_keys = list_all(daily_prefix, fetch=fetch)
            keys = sorted(k for k in daily_keys if k.endswith(".zip") and archive._month_of(k, "daily") == month)
        for key in keys:
            if free_check is not None:
                free_check()
            target = directory / safe_name(Path(key).name)
            try:
                data = download_verified(data_url(key), target, fetch=fetch)
                yield Path(key).name, sha256(data).hexdigest(), data
            finally:
                target.unlink(missing_ok=True)
                target.with_name(target.name + ".CHECKSUM").unlink(missing_ok=True)


def funding_arrays(symbol: str, directory: Path, *, fetch: Any = archive.http_fetch) -> tuple[np.ndarray, np.ndarray]:
    """Funding settlements of ``symbol`` as (v2 grid index, rate fraction) from the monthly fundingRate archive."""
    frame = archive.load_dataset("funding", symbol, start=FIRST_MONTH + "-01", end=FUNDING_END, fetch=fetch,
                                 directory=directory)
    if frame.empty:
        return np.zeros(0, dtype=np.int64), np.zeros(0)
    minutes = np.asarray((frame.index - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(minutes=1), dtype=np.int64)
    idx = minutes - GRID_START_MIN
    keep = (idx >= 0) & (idx < GRID_LEN)
    return idx[keep].astype(np.int64), frame["rate"].to_numpy(dtype=float)[keep]


def span_stats(present: np.ndarray) -> dict[str, Any]:
    """Bar count, first / last bar and gap statistics of a boolean ``present`` vector (v2 grid)."""
    stats: dict[str, Any] = {"bars": int(present.sum())}
    if present.any():
        first, last = int(np.argmax(present)), int(len(present) - 1 - np.argmax(present[::-1]))
        gaps = np.diff(np.flatnonzero(present[first:last + 1])) - 1
        gaps = gaps[gaps > 0]
        stats.update(first_bar_end=str(GRID_START + pd.Timedelta(minutes=first)),
                     last_bar_end=str(GRID_START + pd.Timedelta(minutes=last)),
                     missing_inside_span=int((~present[first:last + 1]).sum()), gap_count=int(len(gaps)),
                     longest_gap_minutes=int(gaps.max()) if len(gaps) else 0, gaps_over_60m=int((gaps > 60).sum()))
    return stats


def remaining_gaps(present: np.ndarray) -> list[dict[str, Any]]:
    """Gaps inside the first..last bar span as ``{start, minutes}`` (start = first missing bar END)."""
    if not present.any():
        return []
    first, last = int(np.argmax(present)), int(len(present) - 1 - np.argmax(present[::-1]))
    miss = np.flatnonzero(~present[first:last + 1]) + first
    if len(miss) == 0:
        return []
    return [{"start": str(GRID_START + pd.Timedelta(minutes=int(g[0]))), "minutes": int(len(g))}
            for g in np.split(miss, np.flatnonzero(np.diff(miss) > 1) + 1)]


def fill_from_daily(hlc: np.ndarray, symbol: str, tmp: Path, *, fetch: Any = archive.http_fetch,
                    free_check: Any = None) -> tuple[np.ndarray, dict[str, Any], list[dict[str, Any]]]:
    """Amendment 1 rule: for every day that has missing minutes inside the symbol's first..last bar span, fill ONLY the
    missing minutes from that day's checksum-verified daily 1m file.  Bars already present (from the monthly files) are
    never overwritten; where both exist and differ (float32-compared) the conflict is counted.  Days without a daily
    file stay NaN."""
    from hashlib import sha256
    hlc = np.array(hlc, dtype=np.float64)
    present = ~np.isnan(hlc[2])
    info: dict[str, Any] = {"days_requested": [], "days_filled": [], "days_without_file": [], "minutes_filled": 0,
                            "overlap_minutes": 0, "conflicting_minutes": 0, "daily_ohlc_violations": 0}
    files: list[dict[str, Any]] = []
    if not present.any():
        info["remaining_gaps"] = []
        return hlc, info, files
    first, last = int(np.argmax(present)), int(len(present) - 1 - np.argmax(present[::-1]))
    miss = np.flatnonzero(~present[first:last + 1]) + first
    if len(miss):
        open_min = GRID_START_MIN + miss - 1  # bar open minute (epoch minutes)
        days = sorted({str(pd.Timestamp(int(m) * 60, unit="s").date()) for m in open_min})
        _, dkeys = list_all(KLINE_1M[1].format(s=symbol), fetch=fetch)
        by_day = {}
        for k in dkeys:
            m = re.search(r"(\d{4}-\d{2}-\d{2})\.zip$", k)
            if m and k.endswith(".zip"):
                by_day[m.group(1)] = k
        tmp.mkdir(parents=True, exist_ok=True)
        for day in days:
            info["days_requested"].append(day)
            key = by_day.get(day)
            if key is None:
                info["days_without_file"].append(day)
                continue
            if free_check is not None:
                free_check()
            target = tmp / safe_name(Path(key).name)
            try:
                data = download_verified(data_url(key), target, fetch=fetch)
                digest = sha256(data).hexdigest()
                frame = parse_minute_zip(data)
            finally:
                target.unlink(missing_ok=True)
                target.with_name(target.name + ".CHECKSUM").unlink(missing_ok=True)
            dgrid, dstats = to_grid(frame)
            info["daily_ohlc_violations"] += dstats["ohlc_violations"]
            dh = dgrid[1:]
            dpres = ~np.isnan(dh[2])
            cur = ~np.isnan(hlc[2])
            both = dpres & cur
            info["overlap_minutes"] += int(both.sum())
            if both.any():
                diff = (dh[:, both].astype(np.float32) != hlc[:, both].astype(np.float32)).any(axis=0)
                info["conflicting_minutes"] += int(diff.sum())
            fill = dpres & ~cur
            if fill.any():
                hlc[:, fill] = dh[:, fill]
                info["minutes_filled"] += int(fill.sum())
                info["days_filled"].append(day)
            files.append({"file": Path(key).name, "sha256": digest, "bytes": len(data)})
    info["remaining_gaps"] = remaining_gaps(~np.isnan(hlc[2]))
    return hlc, info, files


def repair_symbol(symbol: str, out_dir: Path, *, fetch: Any = archive.http_fetch,
                  min_free: int = MIN_FREE_BYTES) -> dict[str, Any]:
    """Apply the daily-fill rule to an already stored symbol (array rewritten as float32 only if minutes were filled)
    and update its ``_entries`` record.  Funding is untouched."""
    entry_path = out_dir / "_entries" / f"{symbol}.json"
    entry = json.loads(entry_path.read_text(encoding="utf-8"))
    hlc = np.array(np.load(out_dir / f"{symbol}.npy"), dtype=np.float64)
    filled, info, files = fill_from_daily(hlc, symbol, out_dir / "_zips" / symbol, fetch=fetch,
                                          free_check=lambda: check_free(out_dir, floor=min_free))
    if info["minutes_filled"]:
        np.save(out_dir / f"{symbol}.npy", filled.astype(np.float32))
        entry.update(span_stats(~np.isnan(filled[2])))
        entry["float32"] = float32_effect(filled)
    entry["daily_fill"] = info
    entry["daily_files"] = files
    shutil.rmtree(out_dir / "_zips" / symbol, ignore_errors=True)
    entry_path.write_text(json.dumps(entry, indent=1), encoding="utf-8")
    return entry


def repair_universe(symbols: list[str], out_dir: Path, *, workers: int = 4,
                    fetch: Any = archive.http_fetch) -> dict[str, Any]:
    started = time.time()
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        list(pool.map(lambda s: repair_symbol(s, out_dir, fetch=fetch), symbols))
    return write_manifest(out_dir, symbols, complete=True, seconds=time.time() - started, stopped=None)


def refresh_funding(symbols: list[str], out_dir: Path, *, fetch: Any = archive.http_fetch) -> dict[str, int]:
    """Re-load the funding arrays through ``FUNDING_END`` (adds the 2024-01-01 00:00 settlement); returns the number of
    rows added per symbol.  Klines are untouched; the caller refreshes the manifest."""
    added = {}
    for sym in symbols:
        old = np.load(out_dir / f"{sym}_funding.npz")["idx"]
        f_idx, f_rate = funding_arrays(sym, out_dir / "_funding_cache", fetch=fetch)
        np.savez(out_dir / f"{sym}_funding.npz", idx=f_idx, rate=f_rate)
        entry_path = out_dir / "_entries" / f"{sym}.json"
        entry = json.loads(entry_path.read_text(encoding="utf-8"))
        entry["funding_rows"] = int(len(f_idx))
        entry_path.write_text(json.dumps(entry, indent=1), encoding="utf-8")
        added[sym] = int(len(f_idx) - len(old))
    write_manifest(out_dir, symbols, complete=True, seconds=0.0, stopped=None)
    return added


def download_symbol(symbol: str, out_dir: Path, *, fetch: Any = archive.http_fetch,
                    min_free: int = MIN_FREE_BYTES) -> dict[str, Any]:
    """Download, verify and store one symbol (float32); returns its provenance entry."""
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out_dir / "_zips" / symbol
    tmp.mkdir(parents=True, exist_ok=True)
    frames, files = [], []
    started = time.time()
    guard = lambda: check_free(out_dir, floor=min_free)  # noqa: E731
    for name, digest, data in iter_kline_zips(symbol, tmp, fetch=fetch, free_check=guard):
        frames.append(parse_minute_zip(data))
        files.append({"file": name, "sha256": digest, "bytes": len(data)})
        del data
    frames = [f for f in frames if len(f)]
    frame = pd.concat(frames) if frames else parse_minute_csv("")
    grid, stats = to_grid(frame)
    hlc, fill_info, daily_files = fill_from_daily(
        np.ascontiguousarray(grid[1:]), symbol, tmp, fetch=fetch, free_check=guard)
    stats.update(span_stats(~np.isnan(hlc[2])))
    effect = float32_effect(hlc)
    check_free(out_dir, need=hlc.size * 4 + SAFETY_BYTES // 3, floor=min_free)
    np.save(out_dir / f"{symbol}.npy", hlc.astype(np.float32))
    f_idx, f_rate = funding_arrays(symbol, out_dir / "_funding_cache", fetch=fetch)
    np.savez(out_dir / f"{symbol}_funding.npz", idx=f_idx, rate=f_rate)
    shutil.rmtree(tmp, ignore_errors=True)
    entry = {"symbol": symbol, "files": files, "zip_bytes": int(sum(f["bytes"] for f in files)), **stats,
             "funding_rows": int(len(f_idx)), "float32": effect, "daily_fill": fill_info,
             "daily_files": daily_files, "seconds": round(time.time() - started, 1)}
    (out_dir / "_entries").mkdir(exist_ok=True)
    (out_dir / "_entries" / f"{symbol}.json").write_text(json.dumps(entry, indent=1), encoding="utf-8")
    return entry


def stale_tail_dates(directory: Path, symbols: list[str]) -> dict[str, str | None]:
    """Start date (UTC) of each symbol's trimmed stale tail (v2 grid); ``None`` = no trim, ``"no bars in sample"``."""
    out: dict[str, str | None] = {}
    for s in symbols:
        grid = np.load(directory / f"{s}.npy", mmap_mode="r")
        close = np.asarray(grid[2], dtype=np.float64)
        if np.isnan(close).all():
            out[s] = "no bars in sample"
            continue
        start = bdata.stale_tail_start(np.asarray(grid[0], dtype=np.float64), np.asarray(grid[1], dtype=np.float64), close)
        out[s] = None if start is None else str(GRID_START + pd.Timedelta(minutes=start))
    return out


def update_manifest_digests(directory: Path) -> dict[str, Any]:
    """Record array digests and stale-tail starts in ``manifest.json`` from the arrays currently on disk."""
    path = directory / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    symbols = [e["symbol"] for e in manifest["symbols"]]
    manifest["array_digests"] = bdata.array_digests(directory, symbols)
    manifest["stale_tail_start"] = stale_tail_dates(directory, symbols)
    path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest


def write_manifest(out_dir: Path, symbols: list[str], *, complete: bool, seconds: float, stopped: str | None) -> dict[str, Any]:
    entries = []
    for s in symbols:
        p = out_dir / "_entries" / f"{s}.json"
        if p.exists():
            entries.append(json.loads(p.read_text(encoding="utf-8")))
    manifest = {"grid_start": str(GRID_START), "grid_len": GRID_LEN, "sample_start_idx": SAMPLE_START_IDX,
                "dtype": "float32", "complete": bool(complete), "stopped_reason": stopped,
                "symbols": entries, "seconds": round(seconds, 1)}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return update_manifest_digests(out_dir)


def download_universe(symbols: list[str], out_dir: Path, *, workers: int = 4, fetch: Any = archive.http_fetch,
                      min_free: int = MIN_FREE_BYTES) -> dict[str, Any]:
    """Download every symbol (threads, resumable through ``_entries``) and write ``manifest.json``.  A
    ``DiskSpaceLow`` stops all workers and writes a manifest marked ``complete = False`` with the finished symbols."""
    started = time.time()
    out_dir.mkdir(parents=True, exist_ok=True)
    stop = threading.Event()
    reason: list[str] = []

    def work(sym: str) -> dict[str, Any] | None:
        if (out_dir / "_entries" / f"{sym}.json").exists():
            return None  # finished in an earlier invocation
        if stop.is_set():
            return None
        try:
            return download_symbol(sym, out_dir, fetch=fetch, min_free=min_free)
        except DiskSpaceLow as exc:
            reason.append(f"{sym}: {exc}")
            stop.set()
            shutil.rmtree(out_dir / "_zips" / sym, ignore_errors=True)
            return None

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        list(pool.map(work, symbols))
    done = [s for s in symbols if (out_dir / "_entries" / f"{s}.json").exists()]
    return write_manifest(out_dir, done, complete=len(done) == len(symbols) and not reason,
                          seconds=time.time() - started, stopped=reason[0] if reason else None)


def coverage_report(directory: Path, symbols: list[str]) -> list[dict[str, Any]]:
    """Per-symbol coverage after the stale-tail rule: first / last bar, trim start, bars trimmed, last tradable bar,
    and the largest single-minute close-to-close move (a collapse / re-denomination flag; data quality only)."""
    out = []
    for s in symbols:
        grid = np.load(directory / f"{s}.npy", mmap_mode="r")
        h, lo, c = (np.asarray(grid[k], dtype=np.float64) for k in range(3))
        valid = np.flatnonzero(~np.isnan(c))
        if len(valid) == 0:
            out.append({"symbol": s, "bars": 0, "note": "no bars in sample"})
            continue
        start = bdata.stale_tail_start(h, lo, c)
        trimmed = int((valid >= start).sum()) if start is not None else 0
        kept = valid if start is None else valid[valid < start]
        stamp = lambda i: str(GRID_START + pd.Timedelta(minutes=int(i)))  # noqa: E731
        cc = c[kept]
        adjacent = np.diff(kept) == 1  # moves that cross a gap are skipped
        ratio = np.where(adjacent, np.abs(cc[1:] / cc[:-1] - 1.0), 0.0) if len(cc) > 1 else np.zeros(0)
        k = int(np.argmax(ratio)) if len(ratio) else None
        out.append({"symbol": s, "bars": int(len(valid)), "first_bar_end": stamp(valid[0]),
                    "last_bar_end": stamp(valid[-1]), "stale_tail_start": None if start is None else stamp(start),
                    "bars_trimmed": trimmed,
                    "last_tradable_bar_end": stamp(kept[-1]) if len(kept) else None,
                    "bars_tradable": int(len(kept)),
                    "max_abs_1m_close_move": float(ratio[k]) if k is not None else None,
                    "max_move_at": stamp(kept[k + 1]) if k is not None else None})
    return out


# ------------------------------------------------------------------------------------------------ samples


def primary_sample() -> dict[str, int]:
    """Primary sample on the v2 cache: 2021-01-01..2023-12-31, halves split 2022-06-30 / 07-01."""
    split = (pd.Timestamp(HALF_1_END) - pd.Timestamp("2021-01-01")).days + 1
    return {"start_idx": SAMPLE_START_IDX, "n_days": PRIMARY_DAYS, "split_day": split}


def consistency_sample() -> dict[str, int]:
    """Consistency sample on the v1 cache: 2024-01-01..2026-09-30 (halves per v1; not used in the reading)."""
    from orderflow_edge_lab import leverage_bracket as lb
    return {"start_idx": bdata.SAMPLE_START_IDX,
            "n_days": (bdata.GRID_LEN - 1 - bdata.SAMPLE_START_IDX) // bdata.MINUTES_PER_DAY,
            "split_day": lb.half_split_day()}
