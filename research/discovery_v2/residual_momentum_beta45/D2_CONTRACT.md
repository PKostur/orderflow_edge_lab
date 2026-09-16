# BTC Residual Momentum beta45 v1 — Binance D2 Replication Contract

Status: **locked before Binance strategy results are run or inspected**.

Candidate freeze commit: `db6bd6b06078ed52fb244a1efadb0ae6a8177718`.

## Purpose

Test the exact frozen `dv2_btc_residual_momentum_beta45_v1` rule on an independent venue/data source: Binance USD-M perpetuals. The historical dates overlap the MEXC hypothesis-generation period, so this is **D2**, not future OOS and not prospective evidence.

## Data

- Source: Binance public USD-M futures REST data.
- Symbols: exact corresponding contracts `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `XRPUSDT`, `DOGEUSDT`, `BNBUSDT`, `ADAUSDT`, `LINKUSDT`, `SUIUSDT`, `ENAUSDT`.
- Window: `2026-01-01T00:00:00Z` through `2026-09-12T00:00:00Z` exclusive.
- Daily perpetual klines and historical funding rates are required.
- Missing required symbol history, non-monotonic timestamps, or unavailable funding fails closed. No symbol may be silently dropped.
- Raw responses are normalized to immutable CSVs and SHA-256 hashed in the artifact manifest.

## Exact rule

No parameter is reselected on Binance.

- 45 prior completed daily returns for each alt and BTC.
- OLS with intercept fit strictly on `t-45 ... t-1`.
- Current completed-day residual = alt return at `t` minus fitted intercept/beta prediction using BTC return at `t`.
- Rank the nine alts.
- Long the two highest residuals; short the two lowest residuals.
- Equal dollar: +25% each long, -25% each short.
- Signal after close `t`; first execution at open `t+1`; hold/rebalance daily.
- 1.0x gross, zero intended net exposure, no pyramiding.
- Actual funding cashflows strictly inside each open-to-open holding interval.
- 10 bps per transaction side on actual portfolio turnover; baseline round-trip convention 20 bps.
- Stress transaction costs at 1.5x and 2.0x.

## Controls and benchmarks

Principal control: exact reversed residual direction on the same timestamps (long lowest residual / short highest residual).

Secondary control: raw-return momentum with the same long-high / short-low construction and timing but no BTC residualization.

Benchmarks: BTC open-to-open buy-and-hold return and equal-weight long-only nine-alt open-to-open return over the comparable usable dates. Benchmarks are descriptive and do not alter the candidate.

## Hard D2 replication gates

The exact candidate is `D2_SOURCE_REPLICATED` only if all are true:

1. Mean net return per completed one-day observation > 0 at baseline friction.
2. Mean net return > 0 at 1.5x transaction friction.
3. Minimum leave-one-symbol-out mean net contribution remains > 0.
4. Best-symbol positive-PnL share <= 50%.
5. Best-calendar-month positive-PnL share <= 50%.
6. Top-five positive-period PnL share <= 50%.
7. Candidate mean net exceeds the principal reversed control mean net by at least **5.0 bps per observation**.
8. All chronology, completeness, execution-timing and funding-causality validity checks pass.

The 95% moving-block-bootstrap lower bound is reported. A positive lower bound strengthens the evidence but is not an additional hard gate because the frozen candidate specification did not define it as mandatory.

## Failure rule

Any failed hard gate closes `dv2_btc_residual_momentum_beta45_v1` as `D2_SOURCE_FAILED`. No Binance-specific retuning, symbol removal, cost reduction, or lookback change is allowed under this candidate ID.

## Pass rule

A D2 pass does not establish a persistent edge. It permits only the next Discovery v2 stages: independent-engine replication of the same frozen rule and separately clocked prospective D4 shadow evidence.
