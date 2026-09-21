# FX Market-State v1 Status

**Current state:** two historical market-state survivors; low historical redundancy; prospective D4 frozen; no trading edge or candidate.

## Frozen universe and source

- EURUSD, GBPUSD, USDJPY, AUDUSD
- Massive 1-minute quote-derived forex aggregates
- 12:00-16:00 UTC, fixed 15-minute decision grid
- exact-minute fail-closed eligibility
- historical FX BBO/tick data is not entitled on the connected plan, so this lane does not make executable-PnL claims

## D0 — July 6-31, 2026

- **FXS-H1 trend-efficiency continuation:** falsified because only 56 triggers were observed versus the frozen minimum of 80. Its average directional target was positive, but the sample gate controls.
- **FXS-H2 volatility-expansion persistence:** survived D0. 107 triggers; pooled future-volatility ratio effect versus control +0.3261; all four pairs positive; both calendar halves positive.
- **FXS-H3 Bollinger-displacement reversion:** survived D0. 139 triggers; pooled signed reversion target +0.9647 bps; pooled hit rate 55.40%; all four pairs positive; both calendar halves positive in mean target.

## D3 historical holdout — August 3-28, 2026

The original freeze called this D2 non-overlap replication. The taxonomy clarification corrects the label to D3 historical holdout because it is non-overlapping history from the same source.

- **FXS-H2:** replicated. 135 triggers; pooled future-volatility ratio effect +0.6961; all four pairs positive.
- **FXS-H3:** replicated. 140 triggers; pooled signed reversion target +1.2312 bps; pooled hit rate 60.71%; all four pairs positive.
- **FXS-H1:** not inspected after its D0 failure.

## Orthogonality / redundancy — September 21, 2026

The predeclared H2/H3 common-eligibility analysis is complete.

- **D0:** 1,264 common-eligible timestamps; 107 H2 triggers; 138 H3 triggers; 19 joint. Jaccard 0.0841; phi 0.0667.
- **D3:** 1,255 common-eligible timestamps; 135 H2 triggers; 140 H3 triggers; 19 joint. Jaccard 0.0742; phi 0.0322.
- The frozen high-redundancy flag is **false** in both windows.
- H2 future-volatility persistence remains positive in both H3=0 and H3=1 strata in both windows.
- H3 signed reversion target remains positive in both H2=0 and H2=1 strata in both windows.
- Joint H2&H3 cells contain only 19 observations in each window, so those small conditional cells are descriptive only.

Decision: keep H2 and H3 as separate state descriptors. Do not combine them into a trading rule.

## Prospective D4

A genuine future same-source D4 is frozen before the first post-freeze analysis session:

- window: **2026-09-21 through 2026-10-02**;
- same four pairs, feature definitions, thresholds, targets, exact-minute policy and decision grid;
- H2 requires >=40 triggers, >=8 sessions, positive pooled triggered-minus-control effect and >=3 positive pairs;
- H3 requires >=40 triggers, >=8 sessions, positive pooled signed target, >50% positive-target fraction and >=3 positive pairs.

No D4 result has been inspected yet.

## Evidence boundary

Current evidence supports only that H2 and H3 identified repeatable and historically non-redundant **market states** in two non-overlapping historical windows from the same source.

It does **not** establish:

- independent-source replication;
- completed genuine D4 evidence;
- executable profitability after spread/fees/slippage;
- a promoted trading candidate;
- live or leveraged trading eligibility.

Strategy-PnL conditioning remains prohibited until prospective D4 is complete.
