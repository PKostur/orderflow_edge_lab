# Discovery v2 Sprint 12 - Pre-result freeze clarification

This clarification is committed before any Sprint 12 market result is produced or inspected. It narrows implementation details only and does not change the frozen hypotheses, model family, training window, threshold, costs, or gates.

## Exact feature formulas at signal index t

All price inputs use completed daily bars through t only.

1. `primary_score_spread_p80_minus_p20` = cross-sectional pandas quantile(0.80) - quantile(0.20) of the primary score vector at t, after dropping non-finite values.
2. `btc_completed_1d_return` = BTC close[t] / close[t-1] - 1.
3. `btc_completed_5d_return` = BTC close[t] / close[t-5] - 1.
4. `btc_wilder_adx14` = the existing repository Wilder ADX14 implementation evaluated at t. No future shift is added because the trade executes at the next daily open after bar t has completed.
5. `btc_realized_volatility_20d_annualized` = sample standard deviation (ddof=1) of BTC close-to-close returns t-19..t multiplied by sqrt(365).
6. `cross_sectional_median_realized_volatility_20d_annualized` = median across symbols of the same 20-return annualized realized-volatility calculation.
7. `cross_sectional_median_alt_btc_correlation_30d` = median Pearson correlation across the nine non-BTC symbols versus BTC using completed returns t-29..t.
8. `cross_sectional_funding_burden_dispersion_prior_3_calendar_days` = P80-P20 across symbols of each symbol's realized funding-rate sum in [execution_open - 3 days, execution_open), divided by 3. Settlements exactly at execution_open are excluded.

If any frozen feature is non-finite, the meta layer returns PASS for that setup.

## Primary score formulas

- Trend acceleration: sum of returns t-4..t minus sum of returns t-9..t-5. BTC ADX14 at t must be >=25 for the primary to propose a setup.
- Low skew: negative pandas unbiased sample skew of returns t-89..t.
- Funding carry: negative realized funding-rate sum in [execution_open - 14 days, execution_open), divided by 14.

Ranking remains long the highest two scores and short the lowest two, 25% absolute weight per selected symbol.

## Meta-label chronology

A historical setup label is the proposed primary target's standalone open-to-open net PnL with realized funding and a forced cash-to-position-to-cash round trip at baseline 10 bps per side.

For a current setup entering at timestamp E, a historical setup may enter the training set only when its exit timestamp is strictly less than E. Labels whose exit timestamp equals E are excluded from the current fit. This is deliberately stricter than what might be operationally observable at the same open.

The latest 80 such prior eligible labeled primary setups are used, with at least 60 required. A single-class training sample causes PASS.

## Evaluation alignment

For each family, candidate, reversed-primary control, ungated-parent control and anti-meta diagnostic are evaluated over the same calendar interval beginning with the first setup date on which the frozen meta model can produce a finite probability using at least 60 strictly prior labeled setups. All intervening calendar days are represented, including zero-exposure PASS days, so transitions to and from cash incur actual turnover costs.
