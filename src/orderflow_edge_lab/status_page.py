"""Regenerate the forward-watch table in STATUS.md from the review-clock config (and, optionally, a
dashboard snapshot). Navigation only: it copies registered facts and never computes verdicts.

The table lives between the markers below; everything else in STATUS.md stays hand-written.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

BEGIN = "<!-- BEGIN GENERATED: forward-watches (scripts/generate_status.py) -->"
END = "<!-- END GENERATED: forward-watches -->"


def _date(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def watch_rows(clock: Mapping[str, Any], snapshot: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    live = {}
    for item in (snapshot or {}).get("items", []):
        if item.get("watch_id"):
            live[item["watch_id"]] = item
    rows = []
    for w in clock["watches"]:
        gate = w.get("review_gate", {})
        if gate.get("type") != "calendar_days" or not w.get("forward_workflow"):
            continue
        start = _date(w["prospective_start_utc"])
        review = start + timedelta(days=int(gate["minimum_days"]))
        item = live.get(w["watch_id"], {})
        rows.append({
            "watch_id": w["watch_id"],
            "config": next((a for a in w.get("canonical_artifacts", []) if a.startswith("config/")), ""),
            "start": start.strftime("%Y-%m-%d"),
            "review": review.strftime("%Y-%m-%d"),
            "days": int(gate["minimum_days"]),
            "workflow": w["forward_workflow"],
            "status": item.get("status") or "see workflow",
            "scored_days": item.get("days"),
        })
    return sorted(rows, key=lambda r: (r["review"], r["watch_id"]))


def render_table(rows: list[dict[str, Any]], generated_utc: str) -> str:
    lines = [
        BEGIN,
        "",
        f"_Generated {generated_utc} from `config/prospective_review_clock_v1.json`"
        " and the latest dashboard snapshot. Do not edit by hand._",
        "",
        "| Watch | Config | Start | Review gate | Earliest review | Status | Scored days |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        days = "–" if r["scored_days"] is None else str(r["scored_days"])
        lines.append(
            f"| `{r['watch_id']}` | {('`' + r['config'] + '`') if r['config'] else '–'} | {r['start']} | {r['days']} calendar days | "
            f"**{r['review']}** | `{r['status']}` | {days} |"
        )
    lines += ["", "No verdict of any kind before a watch's earliest review date; the frozen workflow computes it.", "", END]
    return "\n".join(lines)


def update_status(text: str, block: str, *, heading: str = "## Forward watches (generated)") -> str:
    if BEGIN in text and END in text:
        i, j = text.index(BEGIN), text.index(END) + len(END)
        return text[:i] + block + text[j:]
    anchor = "## Research stop rule"
    insert = f"{heading}\n\n{block}\n\n"
    if anchor in text:
        k = text.index(anchor)
        return text[:k] + insert + text[k:]
    return text.rstrip("\n") + "\n\n" + insert


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Regenerate the forward-watch table in STATUS.md.")
    p.add_argument("--status", default="STATUS.md")
    p.add_argument("--clock", default="config/prospective_review_clock_v1.json")
    p.add_argument("--snapshot", default=None, help="dashboard watches.json (optional)")
    p.add_argument("--check", action="store_true", help="exit 1 if STATUS.md is out of date instead of writing")
    a = p.parse_args(argv)
    clock = json.loads(Path(a.clock).read_text(encoding="utf-8"))
    snap = json.loads(Path(a.snapshot).read_text(encoding="utf-8")) if a.snapshot else None
    generated = (snap or {}).get("generated_utc") or "from config only"
    path = Path(a.status)
    old = path.read_text(encoding="utf-8")
    new = update_status(old, render_table(watch_rows(clock, snap), generated))
    if a.check:
        return 0 if new == old else 1
    path.write_text(new, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
