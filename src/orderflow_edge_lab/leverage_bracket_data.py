"""1-minute Binance USDT-M kline + funding loader for leverage-bracket-study-v1 (descriptive; no keys, no orders).

Reuses ``binance_futures_archive`` / ``binance_spot_archive`` (listing, checksum-verified download, funding loader).
Every kline zip is verified against its ``.CHECKSUM`` sha256 at download time; the sha256 is recorded in a manifest
and the zip is deleted after parsing (the 1m archive is ~2 GB for the universe).  Parsed data are stored per symbol as a
dense minute grid ``(3, N)`` float64 array ``[high, low, close]`` (NaN where the archive has no bar) so that the engine
can index bars by minute.

Grid convention: index ``i`` is the bar END time in minutes since ``GRID_START`` (2023-12-30 00:00 UTC), i.e. the close
at index ``i`` is known at ``GRID_START + i`` minutes.  Funding settlements are mapped to the same grid (rounded to the
minute).  ``SAMPLE_START_IDX`` is the first index whose bar ends at or after 2024-01-01 00:00 UTC.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path
import time
from typing import Any

import numpy as np
import pandas as pd

from orderflow_edge_lab import binance_futures_archive as archive
from orderflow_edge_lab.binance_spot_archive import data_url, download_verified, list_all, safe_name

GRID_START = pd.Timestamp("2023-12-30", tz="UTC")
GRID_END = pd.Timestamp("2026-10-01", tz="UTC")  # last bar END included (the 2026-09-30 23:59 bar)
GRID_START_MIN = int(GRID_START.timestamp() // 60)
GRID_LEN = int((GRID_END - GRID_START) / pd.Timedelta(minutes=1)) + 1
SAMPLE_START = pd.Timestamp("2024-01-01", tz="UTC")
SAMPLE_START_IDX = int((SAMPLE_START - GRID_START) / pd.Timedelta(minutes=1))
MINUTES_PER_DAY = 1440
FIRST_MONTH = "2023-12"
LAST_MONTH = "2026-09"
KLINE_1M = (archive.FUTURES_ROOT + "monthly/klines/{s}/1m/", archive.FUTURES_ROOT + "daily/klines/{s}/1m/")
_COLUMNS = list(archive.KLINE_COLUMNS)


def months_between(first: str, last: str) -> list[str]:
    out = []
    y, m = int(first[:4]), int(first[5:7])
    while f"{y:04d}-{m:02d}" <= last:
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def parse_minute_csv(raw: bytes | str) -> pd.DataFrame:
    """1m kline csv (header optional; ms or us open times) -> frame ``[open, high, low, close]`` indexed by the
    grid index of the bar END (minutes since GRID_START)."""
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
    """Frame of 1m bars -> ``(4, GRID_LEN)`` array [open, high, low, close] (NaN = no bar) and bar statistics."""
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


def iter_kline_zips(symbol: str, directory: Path, *, fetch: Any = archive.http_fetch):
    """Yield ``(file name, sha256, data)`` for the 1m zips of ``symbol`` (monthly where published, else daily)."""
    monthly_prefix, daily_prefix = (p.format(s=symbol) for p in KLINE_1M)
    _, mkeys = list_all(monthly_prefix, fetch=fetch)
    monthly = {archive._month_of(k, "monthly"): k for k in mkeys if k.endswith(".zip")}
    daily_keys: list[str] | None = None
    for month in months_between(FIRST_MONTH, LAST_MONTH):
        keys = [monthly[month]] if month in monthly else None
        if keys is None:
            if daily_keys is None:
                _, daily_keys = list_all(daily_prefix, fetch=fetch)
            keys = sorted(k for k in daily_keys if k.endswith(".zip") and archive._month_of(k, "daily") == month)
        for key in keys:
            target = directory / safe_name(Path(key).name)
            data = download_verified(data_url(key), target, fetch=fetch)
            yield Path(key).name, sha256(data).hexdigest(), data
            target.unlink(missing_ok=True)
            target.with_name(target.name + ".CHECKSUM").unlink(missing_ok=True)


def funding_arrays(symbol: str, directory: Path, *, fetch: Any = archive.http_fetch) -> tuple[np.ndarray, np.ndarray]:
    """Funding settlements of ``symbol`` as (grid index, rate fraction) from the monthly fundingRate archive."""
    frame = archive.load_dataset("funding", symbol, start=FIRST_MONTH + "-01", end="2026-09-30", fetch=fetch,
                                 directory=directory)
    if frame.empty:
        return np.zeros(0, dtype=np.int64), np.zeros(0)
    minutes = np.asarray((frame.index - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(minutes=1), dtype=np.int64)
    idx = minutes - GRID_START_MIN
    keep = (idx >= 0) & (idx < GRID_LEN)
    return idx[keep].astype(np.int64), frame["rate"].to_numpy(dtype=float)[keep]


def download_symbol(symbol: str, out_dir: Path, *, fetch: Any = archive.http_fetch) -> dict[str, Any]:
    """Download, verify and store one symbol; returns its provenance entry."""
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out_dir / "_zips" / symbol
    tmp.mkdir(parents=True, exist_ok=True)
    frames, files = [], []
    started = time.time()
    for name, digest, data in iter_kline_zips(symbol, tmp, fetch=fetch):
        frames.append(parse_minute_zip(data))
        files.append({"file": name, "sha256": digest, "bytes": len(data)})
    frames = [f for f in frames if len(f)]
    frame = pd.concat(frames) if frames else parse_minute_csv("")
    grid, stats = to_grid(frame)
    np.save(out_dir / f"{symbol}.npy", np.ascontiguousarray(grid[1:]))  # high, low, close
    f_idx, f_rate = funding_arrays(symbol, out_dir / "_funding_cache", fetch=fetch)
    np.savez(out_dir / f"{symbol}_funding.npz", idx=f_idx, rate=f_rate)
    return {"symbol": symbol, "files": files, "zip_bytes": int(sum(f["bytes"] for f in files)), **stats,
            "funding_rows": int(len(f_idx)), "seconds": round(time.time() - started, 1)}


def download_universe(symbols: list[str], out_dir: Path, *, workers: int = 6,
                      fetch: Any = archive.http_fetch) -> dict[str, Any]:
    """Download every symbol (threads) and write ``manifest.json`` in ``out_dir``."""
    started = time.time()
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        entries = list(pool.map(lambda s: download_symbol(s, out_dir, fetch=fetch), symbols))
    manifest = {"grid_start": str(GRID_START), "grid_len": GRID_LEN, "sample_start_idx": SAMPLE_START_IDX,
                "symbols": entries, "seconds": round(time.time() - started, 1)}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return update_manifest_digests(out_dir)


def stale_tail_start(high: np.ndarray, low: np.ndarray, close: np.ndarray, *, min_run: int = MINUTES_PER_DAY) -> int | None:
    """Grid index where a trailing run of frozen bars (high == low == the final close, no other price since) of at
    least ``min_run`` bars begins, else ``None``.  Such bars are the archive's placeholders after a contract stopped
    trading (e.g. WAVES after 2024-06-11); a position there could never hit a level, only pay fees."""
    valid = np.flatnonzero(~np.isnan(close))
    if len(valid) == 0:
        return None
    last_close = close[valid[-1]]
    differs = valid[(close[valid] != last_close) | (high[valid] != last_close) | (low[valid] != last_close)]
    start = int(differs[-1]) + 1 if len(differs) else int(valid[0])
    run = int((valid >= start).sum())
    return start if run >= min_run else None


def load_symbol(symbol: str, directory: Path, *, mmap: bool = True, trim_stale: bool = True) -> tuple[
        np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """``(high, low, close, funding_idx, funding_rate)`` of a stored symbol.  With ``trim_stale`` the trailing run of
    frozen placeholder bars (``stale_tail_start``) is set to NaN (not traded)."""
    grid = np.load(directory / f"{symbol}.npy", mmap_mode="r" if mmap else None)
    with np.load(directory / f"{symbol}_funding.npz") as f:
        f_idx, f_rate = f["idx"], f["rate"]
    high, low, close = grid[0], grid[1], grid[2]
    if trim_stale:
        start = stale_tail_start(np.asarray(high), np.asarray(low), np.asarray(close))
        if start is not None:
            high, low, close = (np.array(x) for x in (high, low, close))
            high[start:] = low[start:] = close[start:] = np.nan
    return high, low, close, f_idx, f_rate


def digest_file(path: Path) -> str:
    h = sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def digest_arrays(directory: Path, symbols: list[str]) -> dict[str, str]:
    return {s: digest_file(directory / f"{s}.npy") for s in symbols}


def array_digests(directory: Path, symbols: list[str]) -> dict[str, dict[str, str]]:
    """sha256 of every stored ``SYM.npy`` (klines) and ``SYM_funding.npz``."""
    return {s: {"npy": digest_file(directory / f"{s}.npy"), "npz": digest_file(directory / f"{s}_funding.npz")}
            for s in symbols}


def stale_tail_dates(directory: Path, symbols: list[str]) -> dict[str, str | None]:
    """Start date (UTC) of each symbol's trimmed stale tail; ``None`` = no trim; ``"no bars in sample"`` = no data."""
    out: dict[str, str | None] = {}
    for s in symbols:
        grid = np.load(directory / f"{s}.npy", mmap_mode="r")
        close = np.asarray(grid[2])
        if np.isnan(close).all():
            out[s] = "no bars in sample"
            continue
        start = stale_tail_start(np.asarray(grid[0]), np.asarray(grid[1]), close)
        out[s] = None if start is None else str((GRID_START + pd.Timedelta(minutes=start)).date())
    return out


def update_manifest_digests(directory: Path) -> dict[str, Any]:
    """Record array digests and stale-tail dates in ``manifest.json`` from the arrays currently on disk."""
    path = directory / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    symbols = [e["symbol"] for e in manifest["symbols"]]
    manifest["array_digests"] = array_digests(directory, symbols)
    manifest["stale_tail_start"] = stale_tail_dates(directory, symbols)
    path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest


def verify_manifest_digests(directory: Path, symbols: list[str]) -> None:
    """Raise ``ArchiveError`` unless every stored array matches the digest recorded in the manifest."""
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    recorded = manifest.get("array_digests")
    if not recorded:
        raise archive.ArchiveError("manifest has no array_digests: run scripts/leverage_bracket_update_manifest.py")
    current = array_digests(directory, symbols)
    bad = [s for s in symbols if recorded.get(s) != current[s]]
    if bad:
        raise archive.ArchiveError(f"array digest mismatch: {bad}")
