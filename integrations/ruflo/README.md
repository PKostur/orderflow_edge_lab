# Ruflo meta-harness integration

This integration adds Ruflo around the existing trading-research system. It does not replace DeerFlow, the deterministic `orderflow-multi-agent` checks, or the repository's research/promotion gates.

## Responsibility split

- DeerFlow remains the domain-oriented trading research orchestrator and source of detailed project context.
- Ruflo provides persistent memory, swarm/task coordination, Codex integration, background-worker hooks, and optional MetaHarness/security tooling.
- `orderflow_edge_lab` remains the executable source of truth for data capture, backtests, statistics, risk, promotion, and paper execution.

The repository agents remain bounded to research and paper execution. Ruflo must not expand the live-trading capability boundary.

## Local requirements

- Node.js 20 or newer
- npm/npx
- Python environment for `orderflow-edge-lab`
- optional Codex CLI for Ruflo's Codex MCP integration

Upstream Ruflo requires Node >=20 and supports Codex projects through `AGENTS.md`, `.agents/config.toml`, and `.agents/skills/`.

## Bootstrap

Windows PowerShell:

```powershell
.\integrations\ruflo\bootstrap.ps1
```

macOS/Linux/Git Bash:

```bash
bash integrations/ruflo/bootstrap.sh
```

The bootstrap runs Ruflo's Codex initializer, restores this repository's tracked project-specific agent contract and skill if Ruflo rewrites them, performs diagnostics, initializes a hierarchical specialized swarm, and seeds only non-secret safety/context memories.

It does not create exchange credentials or enable live order transmission.

## Swarm model

Use a hierarchical specialized swarm with these conceptual roles:

1. coordinator: lead adversarial/release manager
2. researcher: research validity/statistics
3. researcher: market data and microstructure
4. reviewer: strategy/backtest validation
5. security-architect: execution safety/risk
6. tester: reliability/CI
7. reviewer: observability/deployment

Ruflo coordinates state and memory. Codex/ChatGPT workers still perform the actual repository changes and tests.

## Memory namespaces

Store durable lessons, never secrets:

- `orderflow/patterns`: validated engineering/research patterns
- `orderflow/experiments`: experiment definitions and immutable result references
- `orderflow/failures`: failed approaches and root causes
- `orderflow/decisions`: accepted architecture/research decisions

Never store API keys, exchange credentials, passwords, account identifiers, or secret-bearing `.env` content in Ruflo memory.

## Recommended capabilities

Use Ruflo core memory/swarm/task capabilities first. Particularly useful optional capabilities for this project are MetaHarness, security audit, observability, and cost tracking if paid model/API routing is introduced later.

Do not enable autonomous live broker/exchange execution plugins.

## Operating loop

1. Search Ruflo memory for relevant prior experiment/failure patterns.
2. Read DeerFlow `orderflow-research` project context.
3. Initialize or reuse the bounded research swarm.
4. Delegate specialist reviews with isolated scopes.
5. Execute code/tests through the normal repository workflow.
6. Require the deterministic `orderflow-multi-agent` release-manager report to be reviewable.
7. Require CI and relevant public-data tests to pass before merge.
8. Store only a distilled successful pattern or failure lesson in Ruflo memory.

Ruflo coordination evidence never substitutes for untouched out-of-sample evidence or the existing candidate/holdout/trial-ledger/promotion chain.
