"""Hyperliquid vault panel collector (hyperliquid-vaults-collection-v1).

Collection only: stores one compact gzip JSONL snapshot per UTC date and carries
earlier dates forward. No return statistic, ranking or persistence measure is
computed here; the declaration forbids analysis until a study is registered.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

SOURCE_URL = "https://stats-data.hyperliquid.xyz/Mainnet/vaults"
TIMEOUT_S = 120
RETRIES = 4

FIELDS = (
    "vaultAddress",
    "name",
    "leader",
    "tvl",
    "isClosed",
    "createTimeMillis",
    "apr",
    "relationship_type",
    "pnl_day_last",
    "pnl_week_last",
    "pnl_month_last",
    "pnl_alltime_last",
    "snapshot_utc",
)


def fetch_snapshot(
    url: str = SOURCE_URL, retries: int = RETRIES, timeout: int = TIMEOUT_S, sleep: Callable[[float], None] = time.sleep
) -> list[dict[str, Any]]:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "orderflow-edge-lab/hyperliquid-vaults-v1"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
            if not isinstance(data, list):
                raise ValueError("vault snapshot is not a JSON list")
            return data
        except Exception as exc:  # noqa: BLE001 - retry on any transport/parse failure
            last = exc
            if attempt < retries - 1:
                sleep(2.0 * (2**attempt))
    raise RuntimeError(f"vault snapshot fetch failed after {retries} attempts: {last}")


def _float(x: Any) -> float | None:
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def _last_pnl(pnls: Any, period: str) -> float | None:
    if not isinstance(pnls, list):
        return None
    for item in pnls:
        if isinstance(item, (list, tuple)) and len(item) == 2 and item[0] == period:
            vals = item[1]
            if isinstance(vals, list) and vals:
                return _float(vals[-1])
            return None
    return None


def compact(snapshot: list[dict[str, Any]], snapshot_utc: str) -> list[dict[str, Any]]:
    rows = []
    for item in snapshot:
        s = item.get("summary") or {}
        rel = s.get("relationship") or {}
        pnls = item.get("pnls")
        rows.append(
            {
                "vaultAddress": s.get("vaultAddress"),
                "name": s.get("name"),
                "leader": s.get("leader"),
                "tvl": _float(s.get("tvl")),
                "isClosed": s.get("isClosed"),
                "createTimeMillis": s.get("createTimeMillis"),
                "apr": _float(item.get("apr")),
                "relationship_type": rel.get("type") if isinstance(rel, dict) else None,
                "pnl_day_last": _last_pnl(pnls, "day"),
                "pnl_week_last": _last_pnl(pnls, "week"),
                "pnl_month_last": _last_pnl(pnls, "month"),
                "pnl_alltime_last": _last_pnl(pnls, "allTime"),
                "snapshot_utc": snapshot_utc,
            }
        )
    return rows


def write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
        for row in rows:
            gz.write((json.dumps(row, sort_keys=True) + "\n").encode("utf-8"))


def read_rows(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _dates(snap_dir: Path) -> list[str]:
    if not snap_dir.is_dir():
        return []
    return sorted(p.name[: -len(".jsonl.gz")] for p in snap_dir.glob("*.jsonl.gz"))


def run(
    prior_dir: Path | None,
    output_dir: Path,
    now: datetime | None = None,
    snapshot: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    snapshot_utc = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    out_snaps = output_dir / "snapshots"
    out_snaps.mkdir(parents=True, exist_ok=True)

    prior_dates: list[str] = []
    if prior_dir is not None:
        prior_snaps = Path(prior_dir) / "snapshots"
        prior_dates = _dates(prior_snaps)
        if Path(prior_dir).resolve() != output_dir.resolve():
            for d in prior_dates:
                shutil.copyfile(prior_snaps / f"{d}.jsonl.gz", out_snaps / f"{d}.jsonl.gz")

    rows = compact(snapshot if snapshot is not None else fetch_snapshot(), snapshot_utc)
    target = out_snaps / f"{today}.jsonl.gz"
    if target.exists() and len(read_rows(target)) >= len(rows):
        pass  # keep the earlier same-day snapshot unless it is missing rows
    else:
        write_rows(target, rows)

    dates = _dates(out_snaps)
    missing = [d for d in prior_dates if d not in dates]
    if missing:
        raise RuntimeError(f"panel shrank: prior dates missing from output: {missing}")

    index: dict[str, Any] = {"dates": dates, "files": {}}
    ever: set[str] = set()
    last_rows: list[dict[str, Any]] = []
    for d in dates:
        p = out_snaps / f"{d}.jsonl.gz"
        r = read_rows(p)
        ever.update(x["vaultAddress"] for x in r if x.get("vaultAddress"))
        last_rows = r
        index["files"][d] = {"rows": len(r), "sha256": _sha256(p)}
    (output_dir / "index.json").write_text(json.dumps(index, indent=2, sort_keys=True), encoding="utf-8")

    report = {
        "collection_id": "hyperliquid-vaults-collection-v1",
        "n_dates": len(dates),
        "first_date": dates[0],
        "last_date": dates[-1],
        "vaults_seen_ever": len(ever),
        "latest_open_count": sum(1 for x in last_rows if x.get("isClosed") is False),
        "latest_closed_count": sum(1 for x in last_rows if x.get("isClosed") is True),
        "claims": {"strategy_promotion_authorized": False, "live_trading_authorized": False},
    }
    (output_dir / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Collect the Hyperliquid vault panel (hyperliquid-vaults-v1).")
    p.add_argument("--prior-dir", type=Path, default=None)
    p.add_argument("--output-dir", type=Path, required=True)
    a = p.parse_args(argv)
    report = run(a.prior_dir, a.output_dir)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
