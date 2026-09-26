# Untouched-coins holdout v1: result

- Protocol: `universal-untouched-coins-holdout-v1`, registered in `8cb2af0`, run once
- Data hash: `ff73a0ebb3ad9a4f…`
- Coins: ZEC, LTC, UNI, DOT, DASH, ETC, BCH (never evaluated by any protocol);
  2020-06 to 2026-09-12, 2,266 days, 20 bps, no funding

## Primary: FAILED (narrowly)

| Sharpe | Newey-West t | Mean daily net | Max drawdown | Pass rule |
| ---: | ---: | ---: | ---: | --- |
| 0.76 | 1.87 | 10.1 bps | −41.5% | mean > 0 and t ≥ 2.0 |

Secondary (descriptive):

- DON8: Sharpe 0.82, t 2.05
- EMA8: Sharpe 0.74, t 1.85
- VOL8: Sharpe 0.38, t 0.97
- Inverse-vol sizing: Sharpe 0.71, t 1.73
- By year: 2020H2 −7%, 2021 +161%, 2022 +11%, 2023 +1%, 2024 +5%, 2025 +23%,
  2026 +36%

## Reading

The effect has the same sign and is weaker than on the development coins; it
misses the pre-registered bar. It is consistent with a real but modest crypto
trend premium, again concentrated in 2021. VOL8 adds the least, as in the
anatomy. The funding-charged secondary was not run because the primary already
fails without funding, and charging funding can only lower returns.
