# Orderflow Edge Lab Agent Contract

This repository uses three cooperating layers. Keep their responsibilities separate.

## Orchestration hierarchy

1. **Ruflo meta-harness** coordinates agent memory, task routing, swarm state, handoffs, and harness-level adversarial checks.
2. **DeerFlow `orderflow-research`** supplies the domain-specific trading-research context and specialist decomposition.
3. **`orderflow_edge_lab`** is the executable source of truth for market data, backtests, statistics, risk, promotion, paper execution, CI, and evidence artifacts.

Ruflo and DeerFlow may coordinate or recommend work. They do not override repository evidence or safety gates.

## Before substantial work

When Ruflo is available:

1. Search Ruflo memory for relevant patterns, experiments, failures, and prior decisions.
2. Read the DeerFlow project context under `integrations/deerflow/skills/custom/orderflow-research/references/`.
3. Inspect current repository state and latest research artifacts.
4. Use the smallest specialist swarm that covers the task.

If Ruflo is unavailable, continue with the repository and DeerFlow guidance rather than blocking the work.

## Specialist ownership

Use bounded roles. Multiple specialists may read the same evidence, but never allow two writers to modify the same worktree concurrently.

- **lead / coordinator**: adversarial reviewer and release manager
- **data integrity researcher**: adapters, sequence continuity, timestamps, causality, provenance
- **research validity researcher**: discovery/validation/holdout separation, dependence, multiple testing, trial accounting
- **strategy reviewer**: signals, fills, costs, slippage, RR, BTC/HTF context, cross-pair transfer
- **execution safety reviewer**: risk, stale-data rejection, approval-bound paper path, reconciliation, kill switch
- **tester**: unit/integration tests, packaging, Linux/Windows CI, workflow failure paths
- **observability reviewer**: hashes, logs, manifests, runtime identity, reproducibility

## Current research rules

- Preserve frozen `discovery-v1` thresholds. Do not retune them batch by batch.
- Treat independent capture batches as the primary dependence clusters.
- Market-condition findings are exploratory until they meet the pre-registered readiness gate.
- Cross-pair results are transfer evidence, not untouched OOS evidence for ENA-discovered conditions.
- The remembered 15m EMA20/50 TradingView result remains an already-inspected development hypothesis, not verified OOS evidence.
- Risk discussions should prefer the stop-based MAE/MFE experiment over raw leverage.
- Realistic spread, fees, slippage, latency/freshness and failure assumptions must not be weakened to improve results.

## Evidence and release gates

A change may merge only after the relevant tests pass and the deterministic `orderflow-multi-agent` report is `reviewable`. Treat the internal release-manager status as a real gate, not merely the GitHub workflow conclusion.

A strategy may not be called profitable without genuine untouched out-of-sample evidence. Promotion must preserve candidate freeze, holdout audit, trial-ledger accounting, economics policy, approval-bound paper/shadow reliability, and reconciliation evidence.

## Live execution boundary

Automatic live broker or exchange order transmission remains disabled. Do not add, enable, or route around this boundary unless explicit promotion criteria are met and the user separately approves a future live-execution step.

## Ruflo memory policy

Store distilled reusable lessons only after evidence exists. Suggested namespaces:

- `orderflow/patterns`
- `orderflow/experiments`
- `orderflow/failures`
- `orderflow/decisions`

Never store API keys, exchange credentials, passwords, account identifiers, secret-bearing `.env` content, or other sensitive values in Ruflo memory.

## Execution rule

Ruflo coordinates. The active coding agent executes the actual repository work, tests, branches, CI inspection, and evidence generation. Never stop after creating a Ruflo task or swarm record and assume the work has been performed.
