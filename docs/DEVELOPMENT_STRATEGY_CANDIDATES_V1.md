# Development strategy candidates v1

**Status: development-only specifications and an offline falsification harness.** This document and its additive catalog do **not** change frozen configs, prospective watches, cost files, or any original strategy module. No order-routing, credentials, network market download, or scheduling capability exists in the harness.

## Why these two candidates

The catalog at [`config/development_strategy_candidates_v1.json`](../config/development_strategy_candidates_v1.json) contains exactly two predeclared candidates:

| Candidate | Mechanism | Deliberate separation from prior failed/redundant lanes |
|---|---|---|
| `DEVQ-IMPACT-ABSORPTION-001` | A strongly one-sided one-second aggressive-flow impulse that does **not** move the midpoint by at least a quarter of the prior spread is treated as passive absorption; test a short reversal. | Not a session phase, BTC alignment, static CVD, or volatility-state transfer. It is a dynamic flow-price-impact divergence. |
| `DEVQ-SPREAD-RESOLUTION-001` | A transient spread widening that resolves while the midpoint remains displaced is treated as quote-resilience; test continuation. | Uses BBO path only—no flow, BTC, session, funding, or D4 volatility-state feature. |

They are nevertheless both microstructure candidates. The harness computes one-second signal-bucket Jaccard overlap and flags progression if it exceeds the catalog’s **0.35** limit. It does not choose a candidate by return. Any future incremental-information test must be separately specified before later data are inspected.

The candidates intentionally do **not** retune or reuse terminal IDs `SESSION_W1_ALIGNED_SHORT_ASIA_OPENING`, `SESSION_W2_ALIGNED_BTC_SHORT_ASIA_OPENING`, or the failed D4 volatility-state relationship. In particular, no UTC-session, BTC, or `local_range_to_spread_15s` rule is used.

## Local point-in-time input contract

The evaluator accepts **only a local JSONL file**. It adapts the records through the existing `normalize_rows` and `attach_prior_bbo` adapter path. It makes no HTTP request.

Every row must be strictly increasing by `observed_at_ns`; equal timestamps are rejected because their causal order is ambiguous.
Each evaluation input must contain **exactly one symbol**; a mixed-symbol export is rejected rather than allowing a BBO history from one instrument to influence another.

```json
{"observed_at_ns": 1760000000000000000, "symbol": "ENA_USDT", "event_type": "quote", "bid": 0.2000, "ask": 0.2001}
{"observed_at_ns": 1760000000100000000, "symbol": "ENA_USDT", "event_type": "trade", "price": 0.2001, "size": 1200.0, "side": "BUY"}
```

| Field | Quote | Trade | Rule |
|---|---:|---:|---|
| `observed_at_ns` | required | required | Positive integer, **strictly increasing** source-observation clock. Exchange timestamps, if present, are ignored for ordering. |
| `symbol` | required | required | Non-empty instrument identifier. A production evaluation should use one immutable source/venue/symbol manifest. |
| `event_type` | `quote` | `trade` | Exactly these lower-case values. |
| `bid`, `ask` | required | optional | Positive and `bid < ask`; trade rows may be causally enriched only from a strictly earlier valid quote. |
| `price`, `size` | — | required | Positive finite values. |
| `side` | — | optional | `BUY`/`SELL` (case-insensitive) when source-supplied; otherwise the existing adapter may quote-classify only from a prior valid BBO. |

A separate JSON input manifest is mandatory:

```json
{
  "schema_version": 1,
  "dataset_id": "local-ena-export-2026-10-06",
  "source_sha256": "<sha256 of exact JSONL bytes>",
  "source_kind": "real_market",
  "partition": "development_only",
  "point_in_time_clock": "observed_at_ns",
  "market_data_visible_during_hypothesis_formation": true,
  "coverage_end_observed_at_ns": 1760000010000000000
}
```

`source_kind` may be `synthetic_test` only for causality and accounting tests. Such a report is explicitly marked **not market evidence**. A mismatched hash, missing point-in-time declaration, wrong partition, invalid/crossed quote, ambiguous time, missing quote stream, or unfinished next-event fill causes an error or an `INCOMPLETE_MISSING_NEXT_EVENT_FILL` result. Partial completed fills are deliberately discarded when any generated signal lacks its required future quote.

## Causality and friction

For both candidates:

1. Feature windows end at the decision event’s `observed_at_ns`.
2. The decision is not filled on that event. Entry is the **first quote strictly later** than the decision plus one millisecond, crossing the ask for a long and bid for a short.
3. Exit is the first quote at or after entry plus the five-second horizon, crossing the bid for a long and ask for a short.
4. Reported gross return therefore includes the observed BBO crossing. Reported net return additionally deducts **2.0 bps round-trip fees and 1.0 bp round-trip slippage** for every fill. Neither cost component may be zero.
5. There is no same-close fill, hindsight reordering, aggregation by exchange timestamp, sizing, leverage, order code, or performance-based selection.

## Commands

Use the repository environment and do not put generated artifacts in frozen research paths.

```bash
cd /home/ubuntu/orderflow-bot-progression/worktrees/strategy
export PYTHONPATH=src:tests

# 1. Hash-pin both rules before inspecting a later evaluation dataset.
python -m orderflow_edge_lab.development_strategy_candidates_v1 \
  --catalog config/development_strategy_candidates_v1.json \
  --freeze-output /tmp/development_strategy_candidates_v1.freeze.json \
  --frozen-at 2026-10-06T00:00:00Z

# 2. Evaluate an already-inspected development export. The command requires the
#    spec freeze and appends exactly one ledger row per candidate; it has no network path.
python -m orderflow_edge_lab.development_strategy_candidates_v1 \
  --catalog config/development_strategy_candidates_v1.json \
  --input /data/immutable/ena_point_in_time.jsonl \
  --input-manifest /data/immutable/ena_point_in_time.manifest.json \
  --candidate-freeze /tmp/development_strategy_candidates_v1.freeze.json \
  --trial-ledger /tmp/development_strategy_candidates_v1.trials.json \
  --recorded-at 2026-10-06T00:00:00Z \
  --output /tmp/development_strategy_candidates_v1.report.json

# 3. Engineering-only tests and lint.
PYTHONPATH=src:tests python -m unittest tests.test_development_strategy_candidates_v1
/home/ubuntu/orderflow-implementation/venv/bin/ruff check \
  src/orderflow_edge_lab/development_strategy_candidates_v1.py \
  tests/test_development_strategy_candidates_v1.py
```

`--freeze-output` creates only the rule-definition manifest and exits; it does not need or read market data. Evaluation mode requires every listed input, freeze, ledger, timestamp, and output path.

## Trial controls and non-promotion boundary

- The candidate-specification freeze pins the exact catalog bytes plus each candidate’s canonical specification hash. It is **not** a research-freeze or holdout audit.
- The evaluator refuses a freeze that does not reproduce the exact catalog bytes or cover exactly the evaluated candidates.
- The ledger is append-only in logical content: a candidate/spec/input-byte triple cannot be counted twice. Each successive candidate run gets a sequential trial number and `family_alpha / trial_number` Bonferroni label. A changed source file is a new source hash and a separately counted trial.
- Candidate output contains `COMPLETED_DEVELOPMENT_ONLY` only when all signals have next-event entry and exit quotes. It never denotes a pass, profitability, OOS evidence, paper readiness, or promotion.
- Any future validation needs its own audited source bytes, `research_freeze`, candidate-boundary/holdout audit, and the repository’s existing holdout trial ledger. Do not relabel development output as holdout evidence.

## Current data gaps

No eligible immutable point-in-time quote-and-trade export, manifest, or independent post-freeze dataset was supplied with this task. Therefore **no strategy has been run, no market performance has been measured, and no new claim is made**. The immediate next work is data integrity, not a performance screen:

1. Produce an immutable local export/manifest with strict `observed_at_ns`, valid BBOs, trade sizes, and enough future quote coverage for every generated signal.
2. Record whether bytes were visible during hypothesis formation; use those bytes only for development if they were inspected.
3. Before any later validation data are opened, create a repository-standard research freeze and use the existing holdout audit/trial-ledger workflow.
4. Treat high candidate overlap, high missing-fill rates, or nonpositive gross/net results as falsification evidence; do not retune these IDs on the same data.
