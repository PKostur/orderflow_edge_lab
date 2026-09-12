# Market-condition and cross-pair research plan

This plan is intentionally pre-specified before cross-pair results are inspected.

## Stage 1: ENA condition stratification

For each frozen order-flow signal, classify only information available at signal time. Primary conditions:

- executable spread in bps: narrow <= 1, medium >1 to 3, wide >3;
- 15-second local price range divided by current spread: low <=2, medium >2 to 6, high >6;
- absolute 15-second local return divided by current spread: flat <=1, moving >1 to 4, strong >4;
- rolling 10-second trade count: sparse <=2, active 3 to 8, intense >=9;
- BTC order-flow alignment: aligned, neutral, against;
- family-normalized signal strength: weak 1.0 to <1.5 threshold multiples, medium 1.5 to <2.5, strong >=2.5;
- UTC session: 00-08, 08-16, 16-24.

For each condition, report trade count, independent batch count, net profit factor, net expectancy in bps, win rate, and the fraction of batches with positive net expectancy for the 5s, 15s and 30s horizons under 4 bps and 8 bps round-trip cost cases.

A condition is not promotable merely because its pooled PF exceeds 1. A screening condition requires at least 20 observations across at least 3 independent capture batches, positive net expectancy, PF > 1, and positive net expectancy in at least two thirds of contributing batches. Until those requirements are met, all condition findings remain exploratory.

## Stage 2: pair pre-screen

Use only public MEXC futures data. Pre-screen USDT perpetuals on current market compatibility, not backtest PnL:

- valid bid and ask;
- spread <= 5 bps;
- 24h quote turnover >= 10 million USDT;
- nonzero 24h range;
- exclude ENA because it is the discovery market;
- exclude BTC because it remains the context market.

Rank passing pairs by quote turnover, then capture the top four candidates plus BTC simultaneously. `apiAllowed` is recorded but is not required for research-only market-data tests.

## Stage 3: unchanged transfer test

Run the same frozen discovery-v1 order-flow thresholds, the same BTC context definition, the same 1s/5s/15s/30s horizons, and the same 0/4/8 bps cost cases on each selected pair. Do not tune thresholds per pair.

For every pair, run the original-versus-reversed directional control and the market-condition report. Cross-pair evidence is only transfer evidence. It does not make an ENA-discovered condition out-of-sample if pair selection or condition definitions used ENA discovery data.

## Promotion boundary

Do not claim a profitable edge until a candidate specification is frozen and then tested on untouched future data. Live order transmission remains disabled.
