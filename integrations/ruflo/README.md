# Ruflo meta-harness integration

This integration adds Ruflo as a coordination and memory layer around the existing trading-research system. It does not replace DeerFlow, the deterministic `orderflow-multi-agent` checks, or the repository's research/promotion gates.

## Responsibility split

- DeerFlow remains the domain-oriented trading research orchestrator and source of project-specific research context.
- Ruflo provides persistent memory, swarm/task coordination, Codex integration, background-worker hooks, and optional MetaHarness/security tooling.
- `orderflow_edge_lab` remains the executable source of truth for data capture, backtests, statistics, risk, promotion, and paper execution.

The repository agents remain bounded to research and paper execution. Ruflo must not expand the live-trading capability boundary.

## Local requirements

- Node.js 20 or newer
- npm/npx
- Python environment for `orderflow-edge-lab`
- Optional Codex CLI if you want Ruflo's Codex MCP/skills integration

Ruflo upstream currently requires Node >=20 and initializes Codex projects through `AGENTS.md`, `.agents/config.toml`, and `.agents/skills/`.

## Bootstrap

Windows PowerShell:

```powershell
.\integrations\ruflo\bootstrap.ps1
```

macOS/Linux/Git Bash:

```bash
bash integrations/ruflo/bootstrap.sh
```

The bootstrap intentionally uses Ruflo's Codex initializer, preserves project-specific `AGENTS.md`, and does not create exchange credentials or enable live order transmission.

## Swarm model

Use a hierarchical specialized swarm with the repository roles mapped as follows:

1. coordinator: lead adversarial/release manager
2. researcher: research validity/statistics
3. researcher: market data and microstructure
4. reviewer: strategy/backtest validation
5. security-architect: execution safety/risk
6. tester: reliability/CI
7. reviewer: observability/deployment

Ruflo coordinates state and memory. Codex/ChatGPT workers still perform the actual repository changes and tests.

## Memory namespaces

Store durable lessons, never secret material:

- `orderflow/patterns`: validated engineering/research patterns
- `orderflow/experiments`: experiment definitions and immutable result references
- `orderflow/failures`: failed approaches and root causes
- `orderflow/decisions`: accepted architecture/research decisions

Never store API keys, exchange credentials, account identifiers, or secret-bearing `.env` content in Ruflo memory.

## Recommended Ruflo capabilities

Use the core Ruflo MCP/swarm/memory functions first. Optional features that fit this project are:

- MetaHarness for orchestration scoring and adversarial harness checks
- security audit for dependency/configuration review
- cost tracker if paid LLM/API routing is introduced later
- observability for structured traces of agent decisions

Do not enable autonomous live broker/exchange execution plugins.

## Operating loop

1. Search Ruflo memory for relevant prior experiment/failure patterns.
2. Read DeerFlow `orderflow-research` project context.
3. Initialize or reuse the bounded research swarm.
4. Delegate specialist reviews with isolated scopes.
5. Execute code/tests through the normal repository workflow.
6. Require the deterministic `orderflow-multi-agent` release-manager report to be reviewable.
7. Require CI and relevant live public-data tests to pass before merge.
8. Store only the distilled successful pattern or failure lesson in Ruflo memory.

Ruflo coordination evidence never substitutes for untouched out-of-sample evidence or the existing candidate/holdout/trial-ledger/promotion chain.
