#!/usr/bin/env python3
"""SubagentStop hook: append one `run` row per tier-agent run to .claude/ledger/runs.jsonl.

Model and token usage come from the subagent transcript (message.model / message.usage, deduplicated by message id;
seen in practice, not a documented schema). Gate verdicts are written separately by scripts/ledger_verdict.py.
Never fails the session: any error is swallowed after a best-effort row.
"""

import datetime
import json
import os
import sys

TIERS = {"Explore": "T0", "worker-low": "T1", "worker": "T2", "worker-high": "T3", "opus-worker": "T4", "reviewer-opus": "T5", "researcher": "R1"}
KEYS = ["input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"]


def parse(path):
    usage, models, stamps, seen = dict.fromkeys(KEYS, 0), set(), [], set()
    if not path or not os.path.exists(path):
        return usage, models, None
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if not isinstance(r, dict):
                continue
            if r.get("timestamp"):
                stamps.append(r["timestamp"])
            m = r.get("message") or {}
            if r.get("type") != "assistant" or not isinstance(m, dict) or m.get("id") in seen:
                continue
            seen.add(m.get("id"))
            if m.get("model"):
                models.add(m["model"])
            for k in KEYS:
                usage[k] += int((m.get("usage") or {}).get(k) or 0)

    def t(s):
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))

    try:
        dur = (t(stamps[-1]) - t(stamps[0])).total_seconds() if len(stamps) > 1 else None
    except ValueError:
        dur = None
    return usage, models, dur


def main():
    p = json.load(sys.stdin)
    agent_type = p.get("agent_type") or ""
    if not agent_type:  # Claude Code's own internal agents (prompt suggestions, /btw)
        return
    tp = os.path.expanduser(p.get("agent_transcript_path") or "")
    usage, models, dur = parse(tp)
    effort = p.get("effort")
    rec = {"kind": "run", "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
           "session_id": p.get("session_id"), "agent_id": p.get("agent_id"), "agent_type": agent_type,
           "tier": TIERS.get(agent_type), "effort_hook": effort.get("level") if isinstance(effort, dict) else effort,
           "models": sorted(models), "usage": usage, "duration_s": dur,
           "last_msg_chars": len(p.get("last_assistant_message") or "")}
    d = os.path.join(os.environ.get("CLAUDE_PROJECT_DIR", "."), ".claude", "ledger")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "runs.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # a ledger problem must never break the session
        print(f"ledger hook: {type(exc).__name__}: {exc}", file=sys.stderr)
