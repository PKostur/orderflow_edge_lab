# Multi-Coin Regime and News-Context Research

This development phase broadens the order-flow experiment without changing the frozen `discovery-v1` signal thresholds.

## PnL-independent coin universe

The transfer workflow first applies the existing MEXC market-compatibility screen. The research universe must satisfy the fixed liquidity/market-quality rules before any strategy result is inspected:

- USDT perpetual contract;
- valid best bid/ask;
- spread no wider than 5 bps at screening time;
- at least 10 million USDT 24-hour quote turnover;
- nonzero 24-hour range;
- stablecoin bases excluded;
- ENA is excluded because it is the original discovery market;
- BTC is reserved as the cross-asset context market;
- obvious TradFi, metals, commodity, equity, index and forex contracts are excluded from the coin panel.

Passing markets are ranked by 24-hour turnover. Strategy PnL is never used in this stage.

## BTC-correlation-diversified panel

From the compatibility-screened candidates, the workflow estimates Pearson correlation of aligned 5-minute simple returns with BTC over the preceding 72 hours. At least 200 overlapping return observations are required.

The development panel contains up to six coins and targets:

- two high-positive BTC-correlation coins with correlation at least 0.65;
- two low-absolute-correlation coins with absolute correlation at most 0.25;
- remaining slots filled deterministically by the lowest remaining BTC correlation, then higher turnover, when the target buckets are sparse.

These are panel-selection rules, not order-flow signal thresholds. They are fixed before the per-pair strategy outputs are inspected and do not use strategy PnL.

## Independent capture batches

Each cross-pair workflow captures the selected panel plus BTC simultaneously for 15 minutes. The workflow is scheduled every three hours after merge so evidence can accumulate across UTC sessions and changing market regimes.

Each capture run is one primary dependence cluster. Individual signals inside a capture must not be treated as independent evidence for promotion.

For every selected coin, the same frozen order-flow logic and economics are applied without per-pair retuning. The workflow records:

- original-versus-reversed directional controls;
- 1, 5, 15 and 30 second horizons from the frozen discovery protocol;
- the pre-registered market-condition dimensions;
- stop-based MAE/MFE research at 1R, 2R and 3R;
- requested equity-risk levels 0.25%, 0.5%, 1%, 1.5%, 2%, 3% and 5%;
- fee-inclusive sizing and the repository exposure cap.

Cross-pair results are transfer/generalization evidence. They are not automatically untouched OOS evidence for a condition discovered on ENA.

## News-event context worker

The `news-context-v1` worker is a separate development-only context study. It uses public RSS headlines from CoinDesk and Cointelegraph and public MEXC candlesticks. No API key or account credential is required.

The worker stores only source metadata, title, URL, publication time and hashes. It does not store article bodies. Symbol matching uses conservative aliases to reduce false attribution.

For matched headlines it records:

- the preceding 15-minute coin and BTC move;
- subsequent 5, 15, 30 and 60 minute coin returns;
- BTC returns over the same horizons;
- coin return minus BTC return as a simple relative-move diagnostic.

The coin-minus-BTC measure is not beta-adjusted abnormal return and must not be described as causal impact. Missing future horizons remain incomplete rather than being imputed.

News context is not a trading filter. It can become a candidate conditioning variable only if a separate specification is frozen before later validation evidence is inspected.

## Promotion boundary

The existing screening readiness gate remains unchanged. A market condition must have at least 20 observations across at least three independent capture batches, positive net expectancy after stated costs, net PF above 1, and positive expectancy in at least two thirds of contributing batches before it can influence a new candidate specification.

Meeting that screening gate is not proof of a profitable edge. A new combined candidate must still be frozen and then tested on later untouched validation data under the repository's promotion and trial-accounting rules.
