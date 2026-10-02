# Chop-regime strategy search: result (no candidate passes)

- Protocol: `chop-regime-search-v1`, declared in `36be8f0` before evaluation
- Books: the trend core outside CHOP, the candidate inside CHOP
- Economics: v3.1 with Binance-proxy funding, 20 bps, inverse-vol sizing, 2020-2026
- Status: descriptive
- Pass rule: beat trend-only in both halves

| Book | Full Sharpe | 2020–23 | 2023–26 | Max drawdown | CHOP-day mean | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| trend_only | 0.77 | 0.23 | 1.13 | −11.4% | +0.30 bp | – |
| C3 squeeze breakout | 0.81 | 0.35 | 1.12 | −9.1% | +0.75 bp | no (by 0.01) |
| C4 trend pullback | 0.65 | 0.14 | 0.98 | −9.3% | −0.29 bp | no |
| chop_flat | 0.62 | 0.18 | 0.93 | −8.5% | −0.68 bp | no |
| C1 Bollinger mean reversion | 0.57 | 0.14 | 0.87 | −9.7% | −0.81 bp | no |
| C2 z-score reversal | 0.55 | 0.26 | 0.75 | −10.0% | −0.99 bp | no |
| C6 funding carry | 0.52 | −0.03 | 0.91 | −9.3% | −1.28 bp | no |
| C5 cross-sectional reversal | 0.24 | −0.22 | 0.55 | −14.9% | −3.12 bp | no |

These books start after the regime-label warm-up, which is why trend_only
shows 0.77 here rather than the core's 1.19.

## Reading

- Every reversal-type strategy loses in crypto CHOP, including the
  market-neutral cross-sectional one. Funding carry loses because the
  funding-receiving side fights the trend.
- The near-miss (C3, squeeze breakout) is itself a trend or breakout
  mechanism. It lowers drawdown but ties in 2023–26 and does not pass.
- Standing aside in CHOP costs money, confirming regime-switch-v1.
- Conclusion: CHOP-labelled crypto still carries (weaker) momentum. Keep
  trend-following through chop. At most, C3 may be registered as a
  forward-only hypothesis for its drawdown benefit.
