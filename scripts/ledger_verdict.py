"""Run a deterministic gate and append its verdict to the escalation ledger. The gate's exit code is the only verdict.

Usage: .venv/Scripts/python scripts/ledger_verdict.py <agent_id> <task_class> <tier> -- <gate command...>
Example: ... ledger_verdict.py a1b2 forward-watch T2 -- .venv/Scripts/python -m unittest tests.test_fast_gates
Exits with the gate's exit code. Green tests mean the software is correct, never that a strategy has an edge.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
TIERS = ("T0", "T1", "T2", "T3", "T4", "T5")


def main(argv: list[str]) -> int:
    ledger = ROOT / ".claude" / "ledger" / "runs.jsonl"
    if argv[:1] == ["--ledger"]:
        ledger, argv = Path(argv[1]), argv[2:]
    if "--" not in argv or argv.index("--") != 3 or len(argv) < 5 or argv[2] not in TIERS:
        print(__doc__, file=sys.stderr)
        return 2
    agent_id, task_class, tier = argv[:3]
    cmd = argv[4:]
    try:
        rc = subprocess.run(cmd, cwd=ROOT).returncode
    except OSError as exc:
        print(f"gate could not start: {exc}", file=sys.stderr)
        rc = 127
    rec = {"kind": "verdict", "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(), "agent_id": agent_id,
           "task_class": task_class, "tier": tier, "gate_cmd": " ".join(cmd), "exit_code": rc, "gate": "pass" if rc == 0 else "fail"}
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    print(json.dumps({"verdict": rec["gate"], "exit_code": rc, "task_class": task_class, "tier": tier}))
    return rc


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
