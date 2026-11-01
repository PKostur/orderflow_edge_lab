"""Summarize the escalation ledger (.claude/ledger/runs.jsonl): learned tier per task class, probes due, token use.

Rules (.claude/skills/README-tiers.md):
  promote  - learned tier = cheapest tier with >= 5 verdicts and a gate pass rate >= 90% over its last 10 verdicts
  demote   - 2 failures in the last 5 verdicts at a tier that had qualified -> one tier up
  probe    - after 10 verdicts at the learned tier with no lower-tier verdict, probe one tier lower (in a worktree)
Usage: .venv/Scripts/python scripts/ledger_report.py [ledger path]
"""

from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
ORDER = ["T0", "T1", "T2", "T3", "T4", "T5"]
USAGE_KEYS = ["input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"]


def load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def _rate(xs: list[dict]) -> float:
    return sum(x["gate"] == "pass" for x in xs) / len(xs) if xs else 0.0


def _qualifies(xs: list[dict]) -> bool:
    return len(xs) >= 5 and _rate(xs[-10:]) >= 0.9


def learned(rows: list[dict]) -> dict[str, dict]:
    by: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for r in sorted((r for r in rows if r.get("kind") == "verdict"), key=lambda r: r["ts"]):
        by[r["task_class"]][r["tier"]].append(r)
    out = {}
    for cls, tiers in by.items():
        tier, note = None, ""
        for t in ORDER:
            if _qualifies(tiers.get(t, [])):
                tier = t
                break
        if tier is None:
            for t in ORDER:
                xs = tiers.get(t, [])
                if len(xs) >= 5 and sum(x["gate"] == "fail" for x in xs[-5:]) >= 2 and _qualifies(xs[:-5]):
                    tier = ORDER[min(ORDER.index(t) + 1, len(ORDER) - 1)]
                    note = f"demoted from {t}: 2+ failures in its last 5"
                    break
        probe_due = False
        if tier is not None and ORDER.index(tier) > 1:
            lower_ts = max((x["ts"] for t in ORDER[:ORDER.index(tier)] for x in tiers.get(t, [])), default="")
            probe_due = sum(x["ts"] > lower_ts for x in tiers.get(tier, [])) >= 10
        evidence = {t: f"{sum(x['gate'] == 'pass' for x in xs[-10:])}/{len(xs[-10:])} pass (n={len(xs)}, since {xs[0]['ts'][:10]})"
                    for t, xs in sorted(tiers.items())}
        out[cls] = {"tier": tier, "note": note, "probe_due": probe_due, "evidence": evidence}
    return out


def tokens_by(rows: list[dict]) -> dict[tuple[str, str], dict[str, int]]:
    usage = {r["agent_id"]: r.get("usage") or {} for r in rows if r.get("kind") == "run" and r.get("agent_id")}
    out: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: dict.fromkeys(USAGE_KEYS, 0))
    for r in rows:
        if r.get("kind") == "verdict" and r.get("agent_id") in usage:
            acc = out[(r["task_class"], r["tier"])]
            for k in USAGE_KEYS:
                acc[k] += int(usage[r["agent_id"]].get(k) or 0)
    return dict(out)


def main(argv: list[str]) -> int:
    rows = load(Path(argv[0]) if argv else ROOT / ".claude" / "ledger" / "runs.jsonl")
    runs = [r for r in rows if r.get("kind") == "run"]
    print(f"{len(runs)} runs, {sum(r.get('kind') == 'verdict' for r in rows)} verdicts")
    for cls, x in sorted(learned(rows).items()):
        print(f"\n{cls}: learned tier {x['tier'] or 'none yet (start at T2)'}{'  ' + x['note'] if x['note'] else ''}"
              f"{'  [probe one tier lower next run]' if x['probe_due'] else ''}")
        for t, e in x["evidence"].items():
            print(f"  {t}: {e}")
    tok = tokens_by(rows)
    if tok:
        print("\ntokens by (class, tier): input / output / cache read / cache write")
        for (cls, t), u in sorted(tok.items()):
            print(f"  {cls} {t}: " + " / ".join(f"{u[k]:,}" for k in USAGE_KEYS))
    unmatched = [r for r in runs if r.get("agent_id") not in {v.get("agent_id") for v in rows if v.get("kind") == "verdict"}]
    if unmatched:
        print(f"\n{len(unmatched)} runs without a gate verdict (agent self-reports do not count)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
