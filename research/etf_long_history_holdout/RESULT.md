# ETF long-history holdout v1: result

- Protocol: `universal-etf-long-history-holdout-v1`, registered in `8cb2af0`, run once
- Data hash: `182e6e25c11db6a9…`
- Universe: 20 ETFs across equity, bonds, commodities, FX and real estate;
  2007-01 to 2026-09 (4,943 days); frozen rules mapped to daily bars at equal
  calendar horizons; 10 bps

## Primary: FAILED (wrong sign)

| Series | Sharpe | Newey-West t | Max drawdown |
| --- | ---: | ---: | ---: |
| Inverse-vol combined (primary) | −0.31 | −1.25 | −31.7% |
| ±1 combined | −0.27 | −1.08 | −38.1% |
| DON8 / EMA8 / VOL8 | −0.17 / +0.04 / −0.78 | −0.69 / 0.18 / −3.07 | |
| Equity / bonds / commodities / FX / real estate | −0.28 / −0.28 / +0.32 / −0.68 / −0.32 | −1.13 / −1.07 / 1.14 / −2.60 / −1.17 | |

By year the book is small and mostly negative, with positive crisis years
(2008 +8.7%, 2020 +3.8%, 2022 +2.5%). Daily correlation with SPY is −0.38.

## Reading

- These fast rules (2–6 week horizons, designed on crypto) do not carry a
  premium in traditional assets over 2007–2026. Only commodities are positive,
  and not significantly. The crisis-year convexity is still present, but it
  does not pay for the bleed in between. This fits the known result that
  traditional-asset time-series momentum works at roughly 3–12-month horizons,
  not at these speeds.
- VOL8 is significantly negative (t −3.07). Its high turnover is a liability
  outside crypto.
- **Consequence for `universal-cross-asset-trend-forward-v1`:** the prior that
  the tradfi sleeves (XAUT, SILVER, USOIL, SPX500, NAS100) add edge with these
  rules is now near zero or negative. They may add breadth of noise, not of
  return. The watch stays frozen and running, since it is honest evidence, but
  its expectation should be read in this light.
- This ETF window has now been used for this rule family. Testing a slower
  (for example 12-month) trend rule on the same data would be data reuse; if
  pursued, it needs different data or a forward-only registration.
