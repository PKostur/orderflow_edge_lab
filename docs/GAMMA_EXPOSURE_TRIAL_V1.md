# Gamma Exposure Trial v1

This lane adds BTC options gamma exposure as research context while the existing frozen forward agents continue unchanged. It is not a strategy retune and cannot authorize live execution.

## Why this is forward-only

Deribit's public option summary exposes current open interest, mark implied volatility, underlying price and interest rate, while the instrument catalog supplies strike, option type, expiry and contract size. Those fields are sufficient to build a current gamma-exposure snapshot. They are not a trustworthy historical open-interest series, so this trial does not manufacture historical GEX by applying today's OI or IV to old prices.

The protocol was frozen before the first gamma snapshot is collected. Historical strategy results may be shown only as baseline context. A strategy outcome becomes gamma-tagged only when a causal gamma snapshot already existed at or before the relevant strategy observation and is no more than 90 minutes old.

## Exposure definitions

For every active BTC option with finite positive time to expiry, mark IV, underlying price and open interest, the trial computes standard Black-Scholes gamma. Instrument gamma exposure per 1 percent underlying move is defined as:

`gamma * open_interest_BTC * contract_size * spot_USD^2 * 0.01`

Gross GEX is the sum of absolute instrument exposure. The signed research proxy assigns calls positive and puts negative and sums them. This **call-minus-put GEX proxy is not observed dealer positioning**. Open interest does not reveal who owns which side, so the report must never call this measured dealer gamma.

The report also aggregates exposure by strike, records the largest positive, negative and absolute gamma levels, computes concentration, and estimates a call-minus-put balance-flip proxy over the frozen 0.60x to 1.40x spot grid. The flip is model-derived context, not a trading trigger.

## Comparison with existing results

Each hourly run preserves the gamma snapshot beside fresh reports from the unchanged ENA 1h, 8h trend and 30d/7d cross-sectional forward agents. The comparison layer records their current forward metrics and, when a prior gamma artifact exists, interval changes under the already-observed gamma context.

The first runs are expected to report insufficient matched history. A descriptive gamma-state comparison requires at least 12 causal forward gamma snapshots. A PnL-by-gamma-state table additionally requires at least 5 completed strategy outcomes. These are minimum reporting guards, not promotion criteria.

No gamma threshold may be selected from strategy PF, expectancy or returns. Any later conditioning rule must be separately frozen before later evidence is inspected and must first demonstrate incremental market-state information under the repository's regime-research process.

## Frozen boundaries

The trial does not modify:

- `discovery-v1` order-flow thresholds;
- the frozen ENA 1h candidate or its ATR stop;
- the frozen 8h EMA24/96 trend candidate;
- the frozen 30d/7d cross-sectional momentum candidate;
- fees, spread, slippage, funding or risk assumptions;
- candidate, holdout, trial-ledger or promotion gates;
- the paper/shadow-only execution boundary.

Automatic live order transmission remains disabled.
