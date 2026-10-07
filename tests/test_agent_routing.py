"""Agent routing and escalation ledger (.claude/agents, .claude/hooks, scripts/ledger_*.py)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ledger_report  # noqa: E402
import sync_frozen_deny_rules  # noqa: E402

AGENTS = ROOT / ".claude" / "agents"
TIERS = {"Explore": "T0", "worker-low": "T1", "worker": "T2", "worker-high": "T3", "opus-worker": "T4", "reviewer-opus": "T5"}
EFFORTS = {"low", "medium", "high", "xhigh", "max"}
FIELDS = {"name", "description", "tools", "disallowedTools", "model", "permissionMode", "maxTurns", "skills", "mcpServers",
          "hooks", "memory", "background", "omitClaudeMd", "effort", "isolation", "color", "initialPrompt", "experimental"}


def frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8").replace("
", "
")  # CRLF checkouts on Windows
    assert text.startswith("---\n"), path
    head = text.split("---\n", 2)[1]
    out = {}
    for line in head.splitlines():
        k, _, v = line.partition(":")
        out[k.strip()] = v.strip()
    return out


class AgentFilesTests(unittest.TestCase):
    def test_every_tier_has_a_valid_agent_file(self):
        for name, tier in TIERS.items():
            fm = frontmatter(AGENTS / f"{name}.md")
            self.assertEqual(fm["name"], name)
            self.assertTrue(fm["description"])
            self.assertTrue(set(fm) <= FIELDS, f"unknown frontmatter keys in {name}: {set(fm) - FIELDS}")
            self.assertTrue(fm["model"].startswith("claude-"), "pin full model IDs")
            if name == "Explore":
                self.assertNotIn("effort", fm)  # Haiku 4.5 does not support effort
                self.assertNotIn("Edit", fm["tools"])
            else:
                self.assertIn(fm["effort"], EFFORTS - {"xhigh", "max"})

    def test_reviewer_is_read_only(self):
        fm = frontmatter(AGENTS / "reviewer-opus.md")
        self.assertEqual(fm["permissionMode"], "plan")
        self.assertNotIn("Edit", fm["tools"])
        self.assertNotIn("Write", fm["tools"])

    def test_probe_tier_is_isolated(self):
        self.assertEqual(frontmatter(AGENTS / "worker-low.md")["isolation"], "worktree")


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.s = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))

    def test_routing_keys(self):
        self.assertEqual(self.s["model"], "claude-opus-5-5")
        self.assertEqual(self.s["modelSettings"]["claude-opus-5-5"]["effortLevel"], "high")
        self.assertEqual(self.s["env"]["CLAUDE_CODE_SUBAGENT_MODEL"], "claude-sonnet-5-5")
        self.assertEqual(self.s["env"]["CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH"], "1")
        self.assertNotIn("CLAUDE_CODE_EFFORT_LEVEL", self.s["env"])  # would flatten every tier
        self.assertNotIn("CLAUDE_CODE_SUBAGENT_MODEL_FORCE", self.s["env"])
        self.assertIn("Agent(general-purpose)", self.s["permissions"]["deny"])
        self.assertIn("Agent(fork)", self.s["permissions"]["deny"])

    def test_frozen_deny_rules_in_sync(self):
        want = {f"Edit(/{p})" for p in sync_frozen_deny_rules.frozen_paths(ROOT)}
        have = {r for r in self.s["permissions"]["deny"] if r.startswith("Edit(")}
        self.assertEqual(want - have, set(), "run scripts/sync_frozen_deny_rules.py")
        self.assertFalse(any(r.startswith("Write(") for r in self.s["permissions"]["deny"]), "Write(path) rules are never consulted")

    def test_hook_matches_only_tier_agents(self):
        entry = self.s["hooks"]["SubagentStop"][0]
        self.assertEqual(set(entry["matcher"].split("|")), set(TIERS))
        h = entry["hooks"][0]
        self.assertTrue(h["async"])
        self.assertIn("/.venv/Scripts/python.exe", h["command"])  # python3 on this machine is the Windows Store stub


class HookTests(unittest.TestCase):
    def run_hook(self, payload: dict, project: str) -> list[dict]:
        env = dict(os.environ, CLAUDE_PROJECT_DIR=project)
        subprocess.run([sys.executable, str(ROOT / ".claude" / "hooks" / "ledger_subagent_stop.py")],
                       input=json.dumps(payload), text=True, env=env, check=True)
        p = Path(project) / ".claude" / "ledger" / "runs.jsonl"
        return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []

    def test_run_row_from_transcript_dedupes_messages(self):
        with tempfile.TemporaryDirectory() as d:
            tp = Path(d) / "agent-x.jsonl"
            msg = {"id": "m1", "model": "claude-sonnet-5-5", "usage": {"input_tokens": 10, "output_tokens": 5,
                                                                        "cache_read_input_tokens": 100, "cache_creation_input_tokens": 7}}
            lines = [{"type": "user", "timestamp": "2026-10-08T10:00:00Z", "message": {}},
                     {"type": "assistant", "timestamp": "2026-10-08T10:00:30Z", "message": msg},
                     {"type": "assistant", "timestamp": "2026-10-08T10:00:31Z", "message": msg},  # same response split
                     {"type": "assistant", "timestamp": "2026-10-08T10:01:00Z",
                      "message": {"id": "m2", "model": "claude-sonnet-5-5", "usage": {"input_tokens": 1, "output_tokens": 2}}}]
            tp.write_text("\n".join(json.dumps(x) for x in lines) + "\nnot json\n", encoding="utf-8")
            rows = self.run_hook({"session_id": "s", "agent_id": "a1", "agent_type": "worker", "agent_transcript_path": str(tp),
                                  "last_assistant_message": "done"}, d)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["kind"], "run")
        self.assertEqual(r["tier"], "T2")
        self.assertEqual(r["models"], ["claude-sonnet-5-5"])
        self.assertEqual(r["usage"], {"input_tokens": 11, "output_tokens": 7, "cache_read_input_tokens": 100,
                                      "cache_creation_input_tokens": 7})
        self.assertEqual(r["duration_s"], 60.0)

    def test_internal_agents_are_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self.run_hook({"agent_id": "a", "agent_type": ""}, d), [])


class VerdictTests(unittest.TestCase):
    def test_gate_exit_code_is_the_verdict(self):
        with tempfile.TemporaryDirectory() as d:
            ledger = Path(d) / "runs.jsonl"
            base = [sys.executable, str(ROOT / "scripts" / "ledger_verdict.py"), "--ledger", str(ledger)]
            ok = subprocess.run(base + ["a1", "forward-watch", "T2", "--", sys.executable, "-c", "pass"])
            bad = subprocess.run(base + ["a2", "forward-watch", "T2", "--", sys.executable, "-c", "raise SystemExit(3)"])
            rows = [json.loads(x) for x in ledger.read_text(encoding="utf-8").splitlines()]
        self.assertEqual((ok.returncode, bad.returncode), (0, 3))
        self.assertEqual([r["gate"] for r in rows], ["pass", "fail"])
        self.assertEqual(rows[1]["exit_code"], 3)

    def test_bad_tier_rejected(self):
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "ledger_verdict.py"), "a", "c", "T9", "--", "x"],
                           capture_output=True)
        self.assertEqual(r.returncode, 2)


def v(cls, tier, gate, i):
    return {"kind": "verdict", "ts": f"2026-10-{i:02d}T00:00:00Z", "agent_id": f"{cls}{tier}{i}", "task_class": cls, "tier": tier,
            "gate": gate}


class ReportTests(unittest.TestCase):
    def test_promote_cheapest_reliable_tier(self):
        rows = [v("c", "T2", "pass", i) for i in range(1, 6)] + [v("c", "T3", "pass", i) for i in range(1, 8)]
        self.assertEqual(ledger_report.learned(rows)["c"]["tier"], "T2")

    def test_needs_five_verdicts(self):
        rows = [v("c", "T2", "pass", i) for i in range(1, 5)]
        self.assertIsNone(ledger_report.learned(rows)["c"]["tier"])

    def test_demote_after_two_recent_failures(self):
        rows = [v("c", "T2", "pass", i) for i in range(1, 9)] + [v("c", "T2", "fail", 9), v("c", "T2", "fail", 10)]
        out = ledger_report.learned(rows)["c"]
        self.assertEqual(out["tier"], "T3")
        self.assertIn("demoted", out["note"])

    def test_probe_due_every_ten(self):
        rows = [v("c", "T2", "pass", i) for i in range(1, 11)]
        self.assertTrue(ledger_report.learned(rows)["c"]["probe_due"])
        rows.append(v("c", "T1", "fail", 11))
        self.assertFalse(ledger_report.learned(rows)["c"]["probe_due"])

    def test_join_usage(self):
        runs = [{"kind": "run", "agent_id": "c T21", "usage": {"input_tokens": 5, "output_tokens": 1}}]
        rows = runs + [dict(v("c", "T2", "pass", 1), agent_id="c T21")]
        self.assertEqual(ledger_report.tokens_by(rows)[("c", "T2")]["output_tokens"], 1)


if __name__ == "__main__":
    unittest.main()
