# Pre-window crypto holdout v1: result

- Protocol: `universal-pre-window-crypto-holdout-v1`, registered in `e622e7c` before evaluation
- Window: 2020-06-05 to 2023-12-31 (1,303 days), MEXC 8h, 9 coins. This data was
  never used by any repository protocol; a repo-wide search found no pre-2024 date.
- Data hash: `95abc5d584bc1a18…` (full value in `artifacts/pre_window_holdout/report.json`)

## Primary (pre-registered): PASSED

The combined equal-capital v3 portfolio, daily net return at 20 bps with no
funding charged:

| Sharpe | Newey-West t | Mean daily net | Max drawdown | Pass rule |
| ---: | ---: | ---: | ---: | --- |
| 1.76 | 3.13 | 24.7 bps | −40.9% | mean > 0 and t ≥ 2.0 |

## Secondary (pre-registered, descriptive)

| | Sharpe | t |
| --- | ---: | ---: |
| DON8 | 1.50 | 2.75 |
| EMA8 | 1.66 | 3.17 |
| VOL8 | 1.37 | 2.43 |
| Inverse-vol sizing | 1.79 | 3.05 (max drawdown −9.5%) |

Returns by year: 2020H2 +52%, 2021 +743%, 2022 −6.6%, 2023 +33%.

## Disclosed sensitivity (not pre-registered)

**Funding.** Binance USDT-M funding history, used as a cross-venue proxy
because MEXC has none before 2025-04. Long funding in 2021 averaged 22–43% a
year per coin.

| | Sharpe | t | Funding drag |
| --- | ---: | ---: | ---: |
| No funding (primary) | 1.76 | 3.13 | – |
| With proxy funding | 1.55 | 2.83 | 11.2%/yr |

**Year dependence (post hoc, descriptive only).** Excluding 2021, the result is
t = 1.40 without funding and 1.16 with it (Sharpe 0.69). The trend book was
roughly flat in the 2022 crash (Sharpe 0.03, or −0.06 with funding).

## Reading

- This is the first pre-registered test on data the rules never saw, and it
  passes, including with funding. It raises the prior that the trend premium
  in this book is real.
- The evidence is concentrated in one regime (2021), matching the anatomy's
  finding that a few large trends carry the P&L. It is not evidence of
  steady, all-weather returns.
- It is a backward holdout, and nine coins amount to about 2 independent bets.
  It supports; it does not prove. Nothing is promoted and nothing is retuned.
- Funding must be charged in every crypto evaluation: it cost 11%/yr in a
  boom, against 1%/yr in 2025–26.
