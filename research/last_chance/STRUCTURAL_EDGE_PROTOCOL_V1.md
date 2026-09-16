# Last-Chance Structural Edge Protocol v1

## Objective

Test a return mechanism that does not require predicting whether crypto prices rise or fall: same-asset cross-exchange perpetual funding dispersion between MEXC Futures and Binance USD-M Futures.

This is separate from the existing frozen ENA, 8h trend, cross-sectional, and Markov shadow candidates. None of those specifications or forward clocks are changed.

## Frozen economic idea

For each symbol, estimate each venue's average daily funding from the prior seven calendar days using only settlements strictly before the decision-day open. If the projected seven-day absolute funding differential is at least 1.25 times the assumed all-in round-trip pair cost:

- if MEXC trailing funding is higher, short MEXC perpetual and long Binance perpetual;
- if Binance trailing funding is higher, long MEXC perpetual and short Binance perpetual;
- otherwise remain flat.

The strategy is 1x gross, split 50/50 between the opposing perpetual legs. There is no directional price signal.

## Accounting

Every held day includes:

1. actual MEXC-versus-Binance open-to-open perpetual price divergence;
2. actual public funding settlements on each held leg;
3. transition costs, with half the frozen round-trip pair cost charged on entry and half on exit; a direction reversal closes and reopens and therefore pays the full round-trip cost.

Cost stress cases are 20, 30, and 40 bps for the complete two-leg round trip. The primary case is 30 bps.

Delta-neutral does not mean risk-free. Exchange default/counterparty risk, outages, half-leg execution risk beyond the stressed cost allowance, collateral friction, and tax are not modeled and remain explicit limitations.

## Causality and validation

Development: 2024-01-01 through 2025-12-31.

Later-period validation: 2026-01-01 through 2026-09-11.

The later period is a validation split for this newly written implementation, but is not represented as globally untouched OOS because the broader research project has already observed 2026 market behavior.

The primary 30 bps version must satisfy all of the following before it can even be considered for a new independent paper-shadow freeze:

- positive development return;
- positive later-period validation return;
- validation annualized Sharpe >= 0.5;
- validation max drawdown no worse than -10%;
- at least 60% of loaded symbols positive in validation;
- an identical reversed-direction control must underperform the real funding-spread direction.

Passing those checks is only a screening result. It does not establish a persistent edge and does not authorize live trading.

## Anti-rescue rule

If the frozen rule fails, do not tune the lookback, cost multiple, holding projection, symbol-specific thresholds, or direction using the failed result. Move to a different structural family instead.
