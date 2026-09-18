# Cross-Market Futures v1

Status: **FROZEN BEFORE NON-CRYPTO RESULTS**

Frozen: 2026-09-17 10:10 UTC

Branch: `research/cross-market-futures-v1`

## Purpose

Create a separate non-crypto research lane for centralized futures without contaminating the existing crypto evidence chain. This is a transfer-discovery experiment, not a crypto candidate promotion path and not D4 validation.

## Frozen market panel

- ES — E-mini S&P 500 (CME)
- NQ — E-mini Nasdaq-100 (CME)
- GC — Gold futures (COMEX)
- CL — WTI Crude Oil futures (NYMEX)

The panel was selected before inspecting strategy PnL, based on liquidity, centralized price discovery, and economic-driver diversity. No market may be swapped after seeing v1 results.

## Frozen transfer hypotheses

The normalized discovery-v1 signal thresholds transfer unchanged:

- aggressive-flow ratio: absolute 0.25
- displayed-book imbalance: absolute 0.25
- normalized microprice edge: absolute 0.20
- minimum trade prints: 5
- same-family/same-direction cooldown: 2 seconds
- horizons: 1s, 5s, 15s, 30s

The question is whether these normalized short-horizon signals retain directional and executable economic information in centralized futures. No market-specific threshold or horizon tuning is allowed in v1.

## Data and rolls

Preferred input is dxFeed/DeepCharts trade and quote data. The existing generic dxFeed adapter and data-quality policy remain the source of truth for timestamps, causal BBO enrichment, aggressor classification, stale/crossed quote handling, and monotonicity.

Event-level research is performed on native contracts only. A capture batch may not mix two native contracts. Continuous/rolling symbols may be used for context, but a synthetic roll jump may never create an event-level signal or fill. Contract/session is part of the dependence cluster.

## Economics

Executable BBO is mandatory for PnL. Longs cross ask and exit bid; shorts cross bid and exit ask. In addition to the observed spread, results are stressed with 0, 1, and 2 total extra round-trip ticks. Exact commissions/exchange fees must be added before any later promotion; zero commissions cannot be used to rescue a result. Leverage remains 1x.

## D0 transfer-survival gate

A family can only justify a new separately frozen candidate ID if it has at least 100 signals, five independent capture sessions, signals in at least three markets, positive pooled expectancy after one additional round-trip tick, beats the fully reversed control at that same friction, has positive net expectancy in at least three markets, and no single market contributes more than 60% of positive PnL. Bootstrap is diagnostic at this stage.

v1 itself cannot promote directly.

## Current evidence

No real futures **tick/order-flow PnL** has been inspected under this frozen H1/H2/H3 protocol.

A separate one-minute **bar-price transfer** lane was run because Massive bar data were available; that lane was falsified at D0 and its post-v1 market-specific replication also failed. Those bar results do not count as evidence for or against this order-flow protocol.

The order-flow engineering path is now frozen and implemented through:

- 1.0-second causal Level-1 quote age;
- native-contract single-session replay;
- bounded dxFeed current-Quote, historical-TimeAndSale, and current-AGGREGATE-depth entitlement probes;
- non-selectable 1s/5s/15s/30s signal composites for family-level D0;
- duplicate-source and root/contract/session binding checks;
- deterministic -300s/-60s/+60s/+300s time-shift placebo;
- deterministic session-cluster bootstrap diagnostic;
- multi-session D0 manifest aggregation.

Historical TimeAndSale alone is insufficient for the full frozen replay: actual Quote event history is required for executable BBO state, and H2 additionally requires true top-10 depth history. Current Quote/Order snapshots can establish live-capture capability but do not certify historical replay.

The remaining blocker is eligible event data or a legitimate external dxFeed stream/export that supplies the required event types.

Persistent edge: **not established**. Candidate promotion: **no**. Live execution: **no**. Leverage: **no**.
