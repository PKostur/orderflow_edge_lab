# Order-Flow Project Command Reference

Run commands from the `orderflow_edge_lab` repository root unless noted otherwise.

## Install / verify

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
orderflow-multi-agent --output artifacts/multi_agent_report.json
```

## Fresh public MEXC capture

```bash
orderflow-mexc-record \
  --symbol ENA_USDT \
  --symbol BTC_USDT \
  --duration-seconds 900 \
  --output-dir artifacts/orderflow
```

This uses public market data and no trading credentials.

## Frozen discovery-v1 backtest

```bash
FEATURE=$(find artifacts/orderflow -name '*_mexc_features.jsonl' -print -quit)
orderflow-backtest "$FEATURE" \
  --symbol ENA_USDT \
  --context-symbol BTC_USDT \
  --output artifacts/orderflow/backtest.json
```

The default backtest configuration must remain identical to `config/orderflow_discovery_v1.json` while discovery-v1 is active.

## Aggregate independent capture batches

```bash
orderflow-discovery-aggregate \
  artifacts/batch_01/backtest.json \
  artifacts/batch_02/backtest.json \
  artifacts/batch_03/backtest.json \
  --protocol config/orderflow_discovery_v1.json \
  --output artifacts/discovery_aggregate.json
```

Use capture batches, not individual event observations, as the primary dependence clusters.

## DeepCharts / dxFeed export audit

```bash
orderflow-export-audit \
  path/to/deepcharts_export.csv \
  --symbol NQ \
  --require-ofi-eligible \
  --output research/deepcharts_export_audit.json
```

Bundle overlapping exports before research when needed:

```bash
orderflow-export-bundle export1.csv export2.csv \
  --symbol NQ \
  --output research/nq_bundle.csv
```

## Research provenance

Freeze partitions before candidate research proceeds into later stages:

```bash
orderflow-research-freeze ...
orderflow-candidate-freeze ...
orderflow-holdout-audit ...
orderflow-trial-ledger ...
orderflow-promotion-check ...
```

Use `--help` on each command for the current schema. Do not invent missing artifact paths or hashes.

## Paper runtime

```bash
orderflow-paper-audit \
  --state runtime/paper-state.json \
  --journal runtime/paper-journal.jsonl

orderflow-runtime-snapshot create \
  --state runtime/paper-state.json \
  --journal runtime/paper-journal.jsonl \
  --output runtime/snapshots/session_start.json
```

Paper submission requires the bound research evidence. Do not bypass candidate freeze, holdout audit, trial ledger, promotion evidence, market freshness, or approval expiry.

## Session closeout

```bash
orderflow-session-audit \
  --snapshot runtime/snapshots/session_start.json \
  --state runtime/paper-state.json \
  --journal runtime/paper-journal.jsonl \
  --output runtime/snapshots/session_closeout.json
```

## GitHub workflows

Important workflows currently include:

- `.github/workflows/ci.yml`
- `.github/workflows/multi-agent-hardening.yml`
- `.github/workflows/orderflow-continuous-discovery.yml`

Prefer reviewing workflow artifacts and source hashes over manually copying summary numbers.

## Prohibited shortcut

Do not add or invoke automatic live broker/exchange order transmission as part of research, migration, or environment setup.