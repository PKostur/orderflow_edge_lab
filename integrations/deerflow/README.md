# DeerFlow migration for orderflow_edge_lab

This directory migrates the orchestration layer of `PKostur/orderflow_edge_lab` into DeerFlow while keeping the trading research engine as its own repository and source of truth.

## Why this architecture

Do not copy the backtester or execution engine into DeerFlow internals. DeerFlow is the multi-agent control plane; `orderflow_edge_lab` remains the research/execution package.

The migration uses a DeerFlow custom skill because DeerFlow discovers user-created skills from `skills/custom/` and injects them only when relevant. The skill delegates six specialist reviews through DeerFlow's built-in `task` tool, while the lead agent acts as adversarial reviewer and release manager.

Specialists:

1. data integrity;
2. research validity/statistics;
3. strategy/backtest validation;
4. execution safety/risk;
5. reliability/CI;
6. observability/deployment.

The lead agent reconciles their findings, challenges unsupported edge claims, and chooses the highest-value safe next action.

## Bootstrap on Windows / PowerShell

From the `orderflow_edge_lab` repository root:

```powershell
.\integrations\deerflow\bootstrap.ps1
```

The script is intentionally idempotent. It:

1. clones `https://github.com/bytedance/deer-flow.git` into a sibling `deer-flow` directory when absent;
2. verifies `Makefile`, `backend/`, `frontend/`, and `config.example.yaml`;
3. runs `make config` only when `config.yaml` is absent;
4. checks whether `docker info` succeeds;
5. uses `make docker-init` when Docker is available, otherwise runs `make check` then `make install`;
6. copies the `orderflow-research` skill into DeerFlow's `skills/custom/` directory;
7. writes a generated `references/local-project.md` with the real local repository paths and current trading-project commit;
8. reports model/environment-variable names referenced by `config.yaml` without opening secret-bearing `.env` files;
9. prints the exact launch command required by DeerFlow's official install boundary.

To deliberately refresh the installed custom skill from this repo later:

```powershell
.\integrations\deerflow\bootstrap.ps1 -UpdateSkill
```

## Bootstrap on macOS / Linux / Git Bash

```bash
bash integrations/deerflow/bootstrap.sh
```

To refresh the installed custom skill:

```bash
UPDATE_SKILL=1 bash integrations/deerflow/bootstrap.sh
```

## Expected setup result

If Docker is installed and the daemon is reachable, the setup stops after `make docker-init`. The next launch command is:

```bash
make docker-start
```

If Docker is unavailable but local prerequisites pass, the setup runs `make install`. The next launch command is:

```bash
make dev
```

This follows DeerFlow's official `Install.md` boundary rather than leaving long-running services behind during setup.

## Model configuration

DeerFlow requires at least one active entry under `models:` in `config.yaml`. The bootstrap script does not invent credentials and does not inspect `.env` files.

For an OpenAI-compatible configuration, use DeerFlow's current `config.example.yaml` as the source of truth and reference credentials through environment variables such as `$OPENAI_API_KEY`. Do not commit real keys.

## Using the migrated project

After DeerFlow is launched, activate the custom skill explicitly when you want the trading-project orchestration:

```text
/orderflow-research Continue the ENA/BTC order-flow research. Inspect the latest repository and discovery evidence, delegate the specialist reviews, and implement the highest-value safe next step.
```

The skill's references carry the project history, current research protocol, command map, multi-agent role boundaries, and safety/promotion rules.

## Source-of-truth rule

Research code, tests, scheduled captures, backtest outputs, promotion artifacts, and paper execution remain in `orderflow_edge_lab`. DeerFlow should orchestrate that repo rather than fork its state into a second implementation.

## Live trading boundary

Migration does not enable live broker/exchange transmission. DeerFlow must preserve the existing approval-bound paper execution and promotion rules. A successful migration or multi-agent run is not evidence of a profitable strategy.
