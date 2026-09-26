# Human-constrained optimization, sessions and regimes (2026-09-26)

**Setup.** The frozen 8h DON8/EMA8 signals are acted on only at human check-in
times, holding at most K coins ranked by trend strength. Execution uses real
MEXC fees, 5 bps slippage per side and funding (from 2025-04), with fixed
quantity. Data: 1h MEXC bars for 17 coins, 2023-03 to 2026-09. Every part of
this data has been seen, so everything below is descriptive. The simulator is
validated against canonical v3 (Sharpe 1.093 vs 1.089, daily correlation 0.91).

## 1. Markowitz across all 51 sleeves (walk-forward, 2021-06 to 2026-09)

| Method | Sharpe | Max drawdown | Monthly turnover |
| --- | ---: | ---: | ---: |
| Equal weight | 0.74 | −38.9% | 0.6% |
| Markowitz, sample | 0.74 | −50.4% | 43% |
| Markowitz, shrunk | 0.68 | −35.0% | 28% |
| Minimum variance | 0.66 | −36.6% | 25% |

Markowitz adds nothing. Its shrunk versions tilt toward VOL8, the weakest
strategy.

## 2. The 48-setting grid (check-ins at CET 09/15/21)

The rank correlation of Sharpe between 2023–24 and 2025–26 is −0.02, so
fine-tuning is noise. The top setting on 2023–24 lands mid-pack in 2025–26 at
0.68. Only structural effects hold in both periods: market orders beat limit
orders (0.64 vs 0.37 in 2025–26, the adverse-selection effect), 5 coins beat 3
(0.58 vs 0.42), and a hold buffer of 2 halves trading. Markowitz vs
inverse-vol and the strategy mix flip sign between periods. All 48 settings
have a positive 2025–26 Sharpe (median 0.5).

**Principled choice** (robust effects plus a-priori defaults): K=5, buffer 2,
market orders, DON8+EMA8, inverse-vol. It returns Sharpe 1.17 in 2023–24 and
0.50 in 2025–26 at about 4.5 trades a week.

## 3. Session timing (principled setting)

| Schedule | Full Sharpe | 2023–24 | 2025–26 |
| --- | ---: | ---: | ---: |
| New York 10:00 (16:00 CET) | 1.04 | 1.12 | 0.96 |
| All three opens | 0.94 | 1.22 | 0.54 |
| UTC 00/08/16 (canonical) | 0.93 | 1.25 | 0.50 |
| CET 09/15/21 (the user's) | 0.89 | 1.17 | 0.50 |
| Tokyo 09 | 0.86 | 1.11 | 0.52 |
| CET 09 + 21 | 0.86 | 1.11 | 0.51 |
| London + New York | 0.84 | 1.08 | 0.49 |
| London 08 / CET 09 only | 0.79 | 1.01 | 0.48 |

Human timing costs little. New York open is the only schedule that held in
2025–26, but it is 1 of 10 tried, so it is a forward hypothesis, not a finding.

## 4. Market regimes (monthly thirds of the 17-coin basket)

| Basket month | Basket mean | Strategy mean | Months positive |
| --- | ---: | ---: | ---: |
| Up | +20.5% | +3.2% (Up with high vol: +6.9%) | 53% |
| Down | −13.9% | +0.6% | 64% |
| Flat | +1.4% | −0.9% | 36% |

Strengths: it earns in trends in either direction and is resilient in
declines. Weaknesses: it bleeds in chop, and its short side captures crashes
late; monthly correlation with the basket is 0.48 in this period. Volatility
level matters much less than direction.

## Next (forward-only, no retuning on this data)

- Pre-register a human-version forward watch: the principled setting at CET
  09/15/21, with the New York 16:00 CET schedule as a pre-declared comparison.
- Any chop filter to address the flat-month bleed must be specified a priori,
  for example with the existing efficiency-ratio labels, and tested forward only.
