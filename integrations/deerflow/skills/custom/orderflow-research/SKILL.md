---
name: orderflow-research
description: Orchestrates the PKostur/orderflow_edge_lab trading-research project using specialist subagents for data integrity, research validity, strategy validation, execution safety, reliability, and observability. Use for ENA/BTC order-flow research, DeepCharts/dxFeed integration, backtesting, paper execution safety, CI, and project refinement.
---

# Order-Flow Research Orchestrator

Use this skill for work on the `orderflow_edge_lab` automated trading research project.

Read `references/project-context.md` before making research or architecture decisions. Read `references/commands.md` before invoking repository commands.

## Core operating rule

The project is research-first. Engineering correctness, attractive charts, in-sample performance, or a positive discovery batch do not establish a profitable edge.

Never claim profitability without genuine untouched out-of-sample evidence that survives realistic economics and the repository's promotion gates.

Automatic live broker/exchange order transmission remains out of scope. Do not implement or enable it unless the repository has explicit evidence for promotion, reliable paper/shadow operation, reconciliation tests, and the user explicitly approves a future live step.

## Repository resolution

The bootstrap process writes `references/local-project.md` into this installed skill with the local `orderflow_edge_lab` path and migration metadata.

If that file exists, use it as the canonical local path. If it does not exist, locate the repository conservatively and do not guess a path.

Do not modify DeerFlow upstream code merely to work around a project-specific need. Prefer changes in `orderflow_edge_lab`, this custom skill, or a later out-of-tree DeerFlow extension.

## Required orchestration pattern

For substantial refinement, backtesting, promotion, or migration tasks, delegate six bounded specialist reviews using the built-in `task` tool. Run up to three in parallel per turn so the default DeerFlow concurrency limit is respected.

### Specialist 1: Data integrity

Delegate with a prompt that asks the worker to inspect only the evidence relevant to:

- MEXC depth/trade sequencing and recovery;
- observation-time causality;
- DeepCharts/dxFeed schema and export eligibility;
- source hashes and provenance;
- timestamp regressions, stale/crossed books, duplicates, and coverage;
- whether derived features are causally valid.

Require concrete file paths, commands, or evidence. Do not ask this worker to judge profitability.

### Specialist 2: Research validity and statistics

Ask the worker to inspect:

- discovery/validation/holdout separation;
- frozen discovery-v1 adherence;
- candidate freeze and holdout binding;
- trial-ledger accounting;
- dependence clustering and pseudo-replication;
- multiple-testing burden;
- whether any OOS claim is actually supported.

The worker must flag threshold tuning performed after inspecting discovery batches.

### Specialist 3: Strategy and backtest validation

Ask the worker to inspect:

- signal definitions;
- spread crossing and fill assumptions;
- fees, slippage, latency, funding, and gap behavior;
- RR variants and comparison fairness;
- BTC context and 15m/1h bias timing;
- 1-minute Bollinger setup integration;
- walk-forward and OOS design;
- whether order flow improves executable expectancy rather than only directional accuracy.

Prioritize the 5 to 15 second microstructure horizon without retuning discovery-v1 thresholds batch by batch.

### Specialist 4: Execution safety and risk

Ask the worker to inspect:

- approval-bound paper execution;
- stale-market rejection;
- sizing and risk limits;
- state/journal integrity;
- kill switches;
- approval expiry;
- reconciliation and recovery;
- any path that could accidentally transmit a live order.

This worker must fail closed on uncertainty.

### Specialist 5: Reliability and CI

Ask the worker to inspect:

- unit/integration tests;
- packaging and installed command smoke tests;
- Linux/Windows compatibility;
- scheduled capture workflows;
- artifact retention and failure preservation;
- retry/reconnect behavior;
- deployment diagnostics.

Require reproducible failures rather than speculative cleanup suggestions.

### Specialist 6: Observability and deployment

Ask the worker to inspect:

- structured logs;
- SHA-256 manifests;
- runtime identity;
- session snapshots and closeouts;
- operator diagnostics;
- research artifact traceability;
- whether a result can be reproduced from source artifacts.

## Lead-agent responsibility

The lead agent is the adversarial reviewer and release manager.

After specialist results return:

1. Reconcile contradictions using repository evidence, not voting.
2. Challenge any unsupported edge claim.
3. Prefer one high-value research or correctness improvement over broad refactoring.
4. Preserve frozen discovery-v1 thresholds unless explicitly starting a new candidate generation after discovery.
5. Keep infrastructure work secondary unless it blocks trustworthy research.
6. If implementation is appropriate, create a branch, make the smallest coherent change, run relevant tests/CI, and merge only after required checks pass.
7. If a step needs something only the user can supply, state the single smallest concrete action needed, then continue all independent work.

## Current empirical priority

The main research question is not simply whether order flow predicts the next move. It is whether order-flow information can improve executable expectancy enough to overcome spread and fees, especially as a selective filter for the existing ENA setup:

```text
1m Bollinger behavior
        +
15m / 1h regime
        +
BTC context
        +
order-flow confirmation
        -> trade / no trade
```

Do not optimize this combined system on the same batches used to discover the idea. A new combined candidate must be frozen before later untouched validation data is inspected.

## DeepCharts / dxFeed priority

Prefer the user's existing DeepCharts/dxFeed access where it can provide better order-flow data at zero additional cost. When a real export is unavailable, continue public MEXC research rather than blocking the project.

Never invent dxFeed entitlements, endpoints, or fields. Audit the actual export or legitimate endpoint before using it as research evidence.

## Completion criteria

A refinement cycle is complete when it includes:

- specialist evidence;
- a lead reconciliation;
- one prioritized next action or implemented change;
- test/CI status when code changed;
- explicit research-evidence status;
- no unsupported profitability claim;
- no live-transmission enablement.
