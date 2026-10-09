"""One-shot monitor run for the scheduled task (no prompts needed: one fixed command).

Steps, each with a timeout: git pull --rebase, dashboard snapshot, STATUS table, one SESSION_STATE.md line,
git add/commit/push. Prints a compact summary for the task to report. Descriptive only; changes nothing else.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = Path("C:/Users/007pe/src/ofel_runs/dashboard")
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")
GH_DIR = r"C:\Program Files\GitHub CLI"
BRANCH = "research/payoff-geometry-v1-1"


def run(cmd: list[str], timeout: int, env: dict | None = None) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout, env=env)
        return p.returncode, (p.stdout + p.stderr)[-2000:]
    except subprocess.TimeoutExpired:
        return 124, f"timeout after {timeout}s: {' '.join(cmd)}"


def summarize(now: str) -> str:
    w = json.loads((OUT / "watches.json").read_text(encoding="utf-8"))
    r = json.loads((OUT / "runs.json").read_text(encoding="utf-8"))
    parts = []
    for item in w["items"]:
        books = item.get("books") or {}
        b = books.get(item.get("primary")) or {}
        cum = b.get("cum")
        tag = item["name"].split(" (")[0][:28]
        if item.get("status") in ("PRE_START", None):
            parts.append(f"{tag} {item.get('status')}")
        else:
            parts.append(f"{tag} {item.get('days')}d" + (f" {100 * cum:+.2f}%" if isinstance(cum, (int, float)) else ""))
    failed = [x["name"] for x in r["items"] if x["conclusion"] in ("failure", "timed_out", "startup_failure")]
    return f"- Monitor {now}: " + "; ".join(parts) + (f". Failed latest: {', '.join(failed)}." if failed else ". All latest runs green.")


def add_state_line(line: str) -> None:
    p = ROOT / "SESSION_STATE.md"
    text = p.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    idx = max((i for i, ln in enumerate(lines) if ln.startswith("- Monitor 20")), default=None)
    if idx is None:
        idx = next((i for i, ln in enumerate(lines) if ln.startswith("- D4:")), len(lines)) - 1
    lines.insert(idx + 1, line + "\n")
    # keep only the 3 most recent monitor lines so the state file stays short
    mon = [i for i, ln in enumerate(lines) if ln.startswith("- Monitor 20")]
    for i in reversed(mon[:-3]):
        del lines[i]
    p.write_text("".join(lines), encoding="utf-8")


def main() -> int:
    env = dict(os.environ)
    env["PATH"] = env.get("PATH", "") + os.pathsep + GH_DIR
    env["PYTHONPATH"] = str(ROOT / "src")
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%MZ")
    steps = [
        ("pull", ["git", "pull", "--rebase", "origin", BRANCH], 180),
        ("snapshot", [PY, "scripts/dashboard_snapshot.py", str(OUT)], 1200),
        ("status", [PY, "scripts/generate_status.py", "--snapshot", str(OUT / "watches.json")], 120),
    ]
    for name, cmd, t in steps:
        code, out = run(cmd, t, env)
        if code != 0 and name == "pull":
            # a concurrent fetch in the same checkout can leave FETCH_HEAD with several refs
            # ("Cannot rebase onto multiple branches"); wait, then pull the branch explicitly once
            time.sleep(30)
            code, out = run(["git", "pull", "--rebase", "origin", BRANCH], t, env)
        if code != 0:
            add_state_line(f"- Monitor {now}: step '{name}' failed (exit {code}); see the task run. {out.strip().splitlines()[-1][:200] if out.strip() else ''}")
            run(["git", "add", "SESSION_STATE.md"], 60, env)
            run(["git", "commit", "-m", f"docs: state: monitor {now}, step {name} failed", "-m",
                 "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"], 60, env)
            run(["git", "push"], 180, env)
            print(json.dumps({"ok": False, "failed_step": name, "exit": code, "tail": out[-600:]}))
            return 1
    line = summarize(now)
    add_state_line(line)
    run(["git", "add", "SESSION_STATE.md", "STATUS.md"], 60, env)
    code, out = run(["git", "commit", "-m", f"docs: state: monitor {now}", "-m",
                     "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"], 60, env)
    pcode, pout = run(["git", "push"], 180, env)
    print(json.dumps({"ok": pcode == 0, "summary": line, "dashboard_files": {k: str(OUT / f"{k}.json") for k in ("summary", "watches", "runs")},
                      "push": pout.strip()[-200:]}))
    return 0 if pcode == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
