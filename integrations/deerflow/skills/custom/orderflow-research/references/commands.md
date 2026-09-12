# Order-Flow Project Command Reference

Run commands from the `orderflow_edge_lab` repository root unless noted otherwise.

## Install / verify

```bash
python -m pip install -e .[research]
python -m unittest discover -s tests -v
orderflow-multi-agent --output artifacts/multi_agent_report.json
```

The `research` extra supplies NumPy/pandas for historical candle hypothesis tests. Core public MEXC order-flow capture remains usable without those optional packages.

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

## Original versus reversed control

```bash
orderflow-direction-pair "$FEATURE" \
  --symbol ENA_USDT \
  --context-symbol BTC_USDT \
  --output artifacts/orderflow/direction_pair.json
```

The paired control must preserve identical signals and timestamps while recalculating opposite-direction bid/ask execution rather than merely negating PnL.

## Incremental exposure stress test

```bash
orderflow-risk-ladder artifacts/orderflow/direction_pair.json \
  --output artifacts/orderflow/risk_ladder.json
```

Defaults test effective exposure multiples 1x, 2x, 5x, 10x, 20x, 30x, 50x, 75x, and 100x under 4 bps and 8 bps fee cases. This is a close-to-close exposure stress test, not exact percent-at-risk or a deployment leverage recommendation. It intentionally does not claim to model intratrade MAE, liquidation price, maintenance margin, or funding. Within each stream/family/horizon, overlapping signals are skipped so risk is not silently stacked.

## Stop-based MAE/MFE risk test

```bash
orderflow-stop-risk "$FEATURE" \
  --symbol ENA_USDT \
  --context-symbol BTC_USDT \
  --rr 1,2,3 \
  --risk-pct 0.25,0.5,1,1.5,2,3,5 \
  --fees-bps 4,8 \
  --max-exposure 100 \
  --output artifacts/orderflow/stop_risk.json
```

This is the preferred risk experiment when discussing percent equity at risk. The technical stop is defined causally from recent observed BBO structure with a minimum spread multiple. Position exposure is sized from `technical stop bps + stated round-trip fee bps`, not stop distance alone, then capped by `--max-exposure`. The report records executable-path MAE/MFE, stop/target/time exits, realized drawdown, profit factor, and original/reversed streams. It still does not model liquidation price, maintenance margin, funding, or market impact, so it is not a live-leverage simulator.

## Historical 15m EMA20/EMA50 hypothesis

```bash
orderflow-ema15m-hypothesis \
  --ena path/to/ena.csv \
  --btc path/to/btc.csv \
  --start 2026-08-09 \
  --split 2026-08-18 \
  --end 2026-08-28 \
  --tick-size 0.00001 \
  --output artifacts/ema15m_hypothesis.json
```

Treat this as a hypothesis test, not a confirmed prior TradingView winner. The exact historical claim that EMA20/EMA50 had the highest profit factor has not been independently recovered from saved artifacts. The test therefore compares the preserved Bollinger/BTC baseline with a causal filter using only completed 15-minute candles: EMA20 > EMA50 permits longs and EMA20 < EMA50 permits shorts. The preserved August data has already been inspected, so results from it are development evidence only and are not OOS.

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
- `.github/workflows/orderflow-exploratory.yml`

Prefer reviewing workflow artifacts and source hashes over manually copying summary numbers.

## Prohibited shortcut

Do not add or invoke automatic live broker/exchange order transmission as part of research, migration, or environment setup.
