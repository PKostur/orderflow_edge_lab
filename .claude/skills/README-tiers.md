# Learned tiers for skills

Tiers: T0 Explore (Haiku 4.5, read-only) · T1 worker-low (Sonnet low, probes only) · T2 worker (Sonnet medium, default) ·
T3 worker-high (Sonnet high) · T4 opus-worker (Opus medium) · T5 reviewer-opus (Opus high, read-only).

## Evidence
- `run` rows: written by `.claude/hooks/ledger_subagent_stop.py` (SubagentStop) into `.claude/ledger/runs.jsonl`.
- `verdict` rows: written only by `scripts/ledger_verdict.py <agent_id> <task_class> <tier> -- <gate>`. The gate's
  exit code is the verdict; an agent's own report of success never counts.
- `.venv/Scripts/python scripts/ledger_report.py` prints the learned tier, probes due and token use per task class.

## Rules (computed by `scripts/ledger_report.py`)
- **Promote:** the learned tier is the cheapest tier with at least 5 verdicts and a gate pass rate of 90% or more over
  its last 10 verdicts.
- **Demote:** 2 gate failures in the last 5 verdicts at the learned tier raise it one step.
- **Down-probe:** after 10 verdicts at the learned tier with no lower-tier verdict, run one tier lower once
  (T1 probes run in a worktree). Record its verdict, but ship the learned tier's output.
- Compare tiers on tokens and pass rate; dollar figures on a subscription are only estimates.

## Writing the tier into a skill
Skills live at `.claude/skills/<name>/SKILL.md`. Use `context: fork` with `agent: <tier agent>`; a `model` or
`effort` field in a non-fork skill would change the orchestrator's own model for that turn. Edit only the Routing
block, never the procedure, and show the user the ledger evidence in the same message.

```markdown
---
name: example-task
description: One line on when to use it.
context: fork
agent: worker
---
## Routing (learned, do not hand-edit without ledger evidence)
- tier: T2 worker (claude-sonnet-5-5, medium)
- gate: .venv/Scripts/python -m unittest tests.test_example
- evidence: 9/10 pass since 2026-10-01; probe T1: 2/4 pass
```
