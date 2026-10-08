"""liquidation-flow-v1 (config/liquidation_flow_v1.json): forward-only collector of OKX public liquidation orders.

Keeps an append-only ledger, a poll log and a frozen universe/ctVal snapshot, and reports descriptive counts only.
No hypothesis statistic is computed here; those are reserved for the review date in the config."""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

DEFAULT_CONFIG = Path("config/liquidation_flow_v1.json")
DEFAULT_BLEND = Path("config/multi_premia_blend_v1.json")
BASE_URL = "https://www.okx.com"
ALIASES = {"FILECOIN": "FIL", "TRUMPOFFICIAL": "TRUMP", "PUMPFUN": "PUMP"}
MAX_GAP_MS = 16 * 3600 * 1000
DAY_MS = 24 * 3600 * 1000
KEY_FIELDS = ("instFamily", "ts", "side", "posSide", "sz", "bkPx")


def get_json(url: str, timeout: int = 30) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "orderflow-edge-lab/liquidation-flow-v1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _get_with_retries(getter: Callable[[str], Any], url: str, retries: int, backoff: float) -> Any:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            payload = getter(url)
            if isinstance(payload, Mapping) and str(payload.get("code", "0")) != "0":
                raise RuntimeError(f"okx code {payload.get('code')}: {str(payload.get('msg'))[:120]}")
            return payload
        except Exception as exc:  # noqa: BLE001 - retried, then re-raised
            last = exc
            if attempt + 1 < retries and backoff:
                time.sleep(backoff * (attempt + 1))
    assert last is not None
    raise last


def _details(page: Mapping[str, Any], inst_family: str) -> list[dict[str, Any]]:
    out = []
    for entry in page.get("data") or []:
        items = entry.get("details") if isinstance(entry, Mapping) and "details" in entry else [entry]
        for d in items or []:
            out.append({"instFamily": inst_family, "ts": int(d["ts"]), "side": d["side"], "posSide": d["posSide"],
                        "sz": float(d["sz"]), "bkPx": float(d["bkPx"])})
    return out


def fetch_liquidations(inst_family: str, *, getter: Callable[[str], Any] = get_json, pause: float = 0.25,
                       retries: int = 3, backoff: float = 1.0, max_pages: int = 200) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    after: int | None = None
    for _ in range(max_pages):
        q = {"instType": "SWAP", "instFamily": inst_family, "state": "filled", "limit": "100"}
        if after is not None:
            q["after"] = str(after)
        url = f"{BASE_URL}/api/v5/public/liquidation-orders?{urllib.parse.urlencode(q)}"
        page = _details(_get_with_retries(getter, url, retries, backoff), inst_family)
        if pause:
            time.sleep(pause)
        if not page:
            break
        rows += page
        oldest = min(r["ts"] for r in page)
        if after is not None and oldest >= after:
            break  # no progress; avoid looping on a repeated page
        after = oldest
    return rows


def fetch_ct_vals(*, getter: Callable[[str], Any] = get_json, retries: int = 3, backoff: float = 1.0) -> dict[str, float]:
    payload = _get_with_retries(getter, f"{BASE_URL}/api/v5/public/instruments?instType=SWAP", retries, backoff)
    out = {}
    for ins in payload.get("data") or []:
        fam = ins.get("instFamily") or ""
        if fam.endswith("-USDT") and str(ins.get("instId", "")).endswith("-USDT-SWAP") and ins.get("ctVal"):
            out[fam] = float(ins["ctVal"])
    return out


def universe(blend_symbols: Iterable[str], ct_vals: Mapping[str, float]) -> list[str]:
    fams = []
    for s in blend_symbols:
        base = s[:-5] if s.endswith("_USDT") else s
        fam = f"{ALIASES.get(base, base)}-USDT"
        if fam in ct_vals and fam not in fams:
            fams.append(fam)
    return sorted(fams)


def row_key(r: Mapping[str, Any]) -> tuple:
    return tuple(r[k] for k in KEY_FIELDS)


def merge(prior_rows: Sequence[dict[str, Any]], new_rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = {row_key(r) for r in prior_rows}
    out = list(prior_rows)
    for r in new_rows:
        k = row_key(r)
        if k not in seen:
            seen.add(k)
            out.append(r)
    return sorted(out, key=lambda r: (r["ts"], r["instFamily"], r["side"], r["posSide"], r["sz"], r["bkPx"]))


def with_notional(rows: Iterable[dict[str, Any]], ct_vals: Mapping[str, float]) -> list[dict[str, Any]]:
    return [dict(r, notional_usd=r["sz"] * ct_vals[r["instFamily"]] * r["bkPx"]) for r in rows]


def _day(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def _day_start_ms(day: str) -> int:
    return int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)


def _complete(poll_ts: Sequence[int], start: int, end: int) -> bool:
    before = [t for t in poll_ts if t < start]
    after = [t for t in poll_ts if t >= end]
    if not before or not after:
        return False
    seq = [max(before)] + [t for t in poll_ts if start <= t < end] + [min(after)]
    return all(b - a <= MAX_GAP_MS for a, b in zip(seq, seq[1:]))


def daily(ledger_rows: Sequence[Mapping[str, Any]], polls: Sequence[Mapping[str, Any]],
          families: Sequence[str] | None = None) -> list[dict[str, Any]]:
    ok_ts: dict[str, list[int]] = {}
    for p in polls:
        for fam, ok in (p.get("ok") or {}).items():
            if ok:
                ok_ts.setdefault(fam, []).append(int(p["ts"]))
    for v in ok_ts.values():
        v.sort()
    fams = sorted(families) if families is not None else sorted(set(ok_ts) | {r["instFamily"] for r in ledger_rows})
    agg: dict[tuple[str, str], dict[str, float]] = {}
    for r in ledger_rows:
        a = agg.setdefault((r["instFamily"], _day(r["ts"])), {"long": 0.0, "short": 0.0, "n": 0})
        notional = r.get("notional_usd", 0.0)
        if r["posSide"] == "long":
            a["long"] += notional
        elif r["posSide"] == "short":
            a["short"] += notional
        a["n"] += 1
    all_ts = [t for v in ok_ts.values() for t in v] + [r["ts"] for r in ledger_rows]
    if not all_ts:
        return []
    d0, d1 = _day_start_ms(_day(min(all_ts))), _day_start_ms(_day(max(all_ts)))
    out = []
    for fam in fams:
        d = d0
        while d <= d1:
            day = _day(d)
            a = agg.get((fam, day), {"long": 0.0, "short": 0.0, "n": 0})
            out.append({"instFamily": fam, "day": day, "long_liq_usd": a["long"], "short_liq_usd": a["short"],
                        "n": int(a["n"]), "complete": _complete(ok_ts.get(fam, []), d, d + DAY_MS)})
            d += DAY_MS
    return out


def build_report(cfg: Mapping[str, Any], ledger_rows: Sequence[Mapping[str, Any]], polls: Sequence[Mapping[str, Any]],
                 daily_rows: Sequence[Mapping[str, Any]], meta: Mapping[str, Any], *, now: datetime) -> dict[str, Any]:
    start = datetime.fromisoformat(cfg["prospective_start_utc"].replace("Z", "+00:00"))
    complete = [d for d in daily_rows if d["complete"]]
    by_day: dict[str, dict[str, float]] = {}
    for d in daily_rows:
        t = by_day.setdefault(d["day"], {"long_liq_usd": 0.0, "short_liq_usd": 0.0, "n": 0, "complete_coins": 0})
        t["long_liq_usd"] += d["long_liq_usd"]
        t["short_liq_usd"] += d["short_liq_usd"]
        t["n"] += d["n"]
        t["complete_coins"] += bool(d["complete"])
    return {
        "watch_id": cfg["watch_id"],
        "status": "PRE_START" if now < start else "COLLECTING",
        "run_utc": now.isoformat(),
        "prospective_start_utc": cfg["prospective_start_utc"],
        "review_after_days": cfg["reporting"]["review_after_days"],
        "first_run_utc": meta.get("first_run_utc"),
        "ledger_rows": len(ledger_rows),
        "polls": len(polls),
        "coins": len(meta.get("universe", [])),
        "coin_days": len(daily_rows),
        "complete_coin_days": len(complete),
        "totals_by_day": {k: by_day[k] for k in sorted(by_day)},
        "claims": cfg["claims"],
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8")


def run(cfg: Mapping[str, Any], blend_symbols: Sequence[str], prior_dir: Path | None, output_dir: Path, *,
        now: datetime | None = None, liq_fetcher: Callable[[str], list[dict[str, Any]]] = fetch_liquidations,
        ct_fetcher: Callable[[], dict[str, float]] = fetch_ct_vals) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    prior_ledger = _read_jsonl(prior_dir / "ledger.jsonl") if prior_dir else []
    prior_polls = _read_jsonl(prior_dir / "polls.jsonl") if prior_dir else []
    meta_path = prior_dir / "meta.json" if prior_dir else None
    if meta_path and meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))  # universe and ctVal snapshot are frozen
    else:
        ct = ct_fetcher()
        uni = universe(blend_symbols, ct)
        meta = {"universe": uni, "ct_vals": {f: ct[f] for f in uni}, "first_run_utc": now.isoformat()}
    ok: dict[str, bool] = {}
    fetched: list[dict[str, Any]] = []
    for fam in meta["universe"]:
        try:
            fetched += liq_fetcher(fam)
            ok[fam] = True
        except Exception:  # noqa: BLE001 - recorded as a failed poll for this family
            ok[fam] = False
    ledger = merge(prior_ledger, with_notional(fetched, meta["ct_vals"]))
    polls = prior_polls + [{"ts": int(now.timestamp() * 1000), "ok": ok, "rows": len(fetched)}]
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    _write_jsonl(out / "ledger.jsonl", ledger)
    _write_jsonl(out / "polls.jsonl", polls)
    (out / "meta.json").write_text(json.dumps(meta, indent=1, sort_keys=True), encoding="utf-8")
    drows = daily(ledger, polls, meta["universe"])
    (out / "daily.json").write_text(json.dumps(drows, indent=1, sort_keys=True), encoding="utf-8")
    report = build_report(cfg, ledger, polls, drows, meta, now=now)
    (out / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Collect OKX liquidation orders (liquidation-flow-v1).")
    p.add_argument("--config", default=str(DEFAULT_CONFIG))
    p.add_argument("--blend", default=str(DEFAULT_BLEND))
    p.add_argument("--prior-dir", default=None)
    p.add_argument("--output-dir", required=True)
    a = p.parse_args(argv)
    cfg = json.loads(Path(a.config).read_text(encoding="utf-8"))
    symbols = json.loads(Path(a.blend).read_text(encoding="utf-8"))["symbols"]
    prior = Path(a.prior_dir) if a.prior_dir and Path(a.prior_dir).exists() else None
    report = run(cfg, symbols, prior, Path(a.output_dir))
    failed = sorted(f for f, ok in json.loads((Path(a.output_dir) / "polls.jsonl").read_text().splitlines()[-1])["ok"].items() if not ok)
    print(json.dumps({"status": report["status"], "ledger_rows": report["ledger_rows"], "failed_families": failed}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
