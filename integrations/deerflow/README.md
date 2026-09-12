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

The script is intentionally idempotent. It clones DeerFlow when absent, follows the repository's official config and install path, installs the `orderflow-research` custom skill, binds the real local trading-repo path, and preserves existing config/secrets.

Because this project explicitly requires launch verification, the bootstrap can also start DeerFlow and verify that `http://localhost:2026` responds:

```powershell
.\integrations\deerflow\bootstrap.ps1 -Launch
```

When Docker is available this uses `make docker-start`. Without Docker it uses DeerFlow's `make dev-daemon` after the official local install succeeds. Launch mode refuses to continue when no active model is configured.

To deliberately refresh the installed custom skill from this repo later:

```powershell
.\integrations\deerflow\bootstrap.ps1 -UpdateSkill -Launch
```

## Bootstrap on macOS / Linux / Git Bash

Setup only:

```bash
bash integrations/deerflow/bootstrap.sh
```

Setup, launch, and HTTP verification:

```bash
LAUNCH=1 bash integrations/deerflow/bootstrap.sh
```

To refresh the installed custom skill:

```bash
UPDATE_SKILL=1 LAUNCH=1 bash integrations/deerflow/bootstrap.sh
```

## What the bootstrap follows

The bootstrap mirrors DeerFlow's official `Install.md` decisions:

- validates the DeerFlow repository root;
- runs `make config` only if `config.yaml` is absent;
- detects Docker with `docker info`;
- uses `make docker-init` for the Docker path;
- otherwise runs `make check` and `make install` for local development;
- does not invent model credentials;
- does not inspect secret-bearing `.env` files;
- preserves existing configuration values.

Without launch mode it prints the exact official next command. With launch mode it starts services and polls `http://localhost:2026` until DeerFlow responds or the verification fails.

## Model configuration

DeerFlow requires at least one active entry under `models:` in `config.yaml`. The bootstrap script does not invent credentials and does not inspect `.env` files.

For an OpenAI-compatible configuration, use DeerFlow's current `config.example.yaml` as the source of truth and reference credentials through environment variables such as `$OPENAI_API_KEY`. Do not commit real keys.

## Using the migrated project

After DeerFlow is launched, activate the custom skill explicitly when you want the trading-project orchestration:

```text
/orderflow-research Continue the ENA/BTC order-flow research. Inspect the latest repository and discovery evidence, delegate the specialist reviews, and implement the highest-value safe next step.
```

The skill's references carry the project history, current research protocol, command map, multi-agent role boundaries, safety/promotion rules, and the migrated recurring research task.

## Source-of-truth rule

Research code, tests, scheduled captures, backtest outputs, promotion artifacts, and paper execution remain in `orderflow_edge_lab`. DeerFlow should orchestrate that repo rather than fork its state into a second implementation.

## Live trading boundary

Migration does not enable live broker/exchange transmission. DeerFlow must preserve the existing approval-bound paper execution and promotion rules. A successful migration or multi-agent run is not evidence of a profitable strategy.
