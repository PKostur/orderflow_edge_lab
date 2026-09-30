# Strategy zoo v1 (`strategy-zoo-v1`, declared `fbe22f6`, run once): ALL SEVEN FAIL

Seven untested families, one a-priori parameter set each, 20 bps, funding proxy. Development = 70 coins, confirmation =
60 untouched coins (BTC used as a signal-only context series there). Pass = dev t ≥ 2 with both halves positive AND
confirmation Sharpe > 0 with t ≥ 1.5.

| Family | Dev Sharpe | Dev t | Dev halves | Dev max DD | Conf Sharpe | Conf t | Blend 3→4 legs (dev / conf) |
| --- | ---: | ---: | --- | ---: | ---: | ---: | --- |
| Z1 weekend long | 0.75 | 1.87 | 0.97 / 0.52 | −62% | 0.66 | 1.62 | 2.09→2.13 / 1.39→1.40 |
| Z2 BTC lead-lag (alts follow BTC's ±2% day) | −1.01 | −2.66 | −1.41 / −0.50 | −99% | −1.00 | −2.61 | 2.09→1.35 / 1.39→0.75 |
| Z3 residual reversal (vs BTC beta) | −0.33 | −0.78 | −0.01 / −0.78 | −82% | −1.25 | −3.00 | 2.13→1.99 / 1.37→0.65 |
| Z4 MAX / lottery (short biggest 1-day jump) | −1.02 | −2.43 | −0.88 / −1.33 | −95% | −0.96 | −2.57 | 2.09→1.69 / 1.39→0.83 |
| Z5 180-day-high proximity | −0.05 | −0.11 | −0.16 / 0.04 | −40% | 0.59 | 1.25 | 1.70→1.50 / 1.25→1.21 |
| Z6 volume shock (attention) | 0.01 | 0.02 | −0.20 / 0.29 | −60% | 0.10 | 0.23 | 2.02→1.63 / 1.25→1.10 |
| Z7 skewness (long negative skew) | −0.84 | −2.20 | −0.97 / −0.75 | −88% | −0.02 | −0.07 | 2.13→1.72 / 1.37→1.16 |

## By market regime (annualized Sharpe; labels causal, defined before results; descriptive only)

| Family | CHOP | MIXED | TREND | High vol | Low vol | Bear | Bull |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Z1 weekend (dev / conf) | −0.3 / −0.3 | −1.0 / +0.4 | **+3.8 / +1.9** | +1.2 / +0.8 | +0.3 / +0.5 | 0.0 / −0.1 | +1.4 / +1.6 |
| Z2 BTC lead-lag | −1.6 / −1.8 | −1.2 / −0.1 | −0.5 / −1.1 | −1.7 / −1.5 | −0.3 / −0.4 | −0.9 / −0.6 | −1.2 / −1.4 |
| Z4 MAX / lottery | −0.4 / −0.8 | −1.9 / −1.5 | −0.9 / −0.8 | −1.1 / −0.9 | −0.9 / −1.0 | −0.7 / −1.2 | −1.3 / −0.8 |
| Z5 high proximity | +0.2 / 0.0 | +0.2 / +1.3 | −0.5 / +0.4 | −0.4 / +0.5 | +0.3 / +0.7 | −0.9 / +0.4 | +0.8 / +0.8 |
| Z3, Z6, Z7 | mixed signs, no regime positive in both samples | | | | | | |

## Reading
- No family earns a premium that survives both samples; none should be traded or added to the blend.
- Two are reliably *wrong-signed* in both samples and nearly every regime: **Z2** (after a big BTC day, alts reverse
  rather than follow) and **Z4** (the biggest one-day jumpers keep outperforming: lottery momentum, not reversal).
  The mirror strategies are new hypotheses chosen after seeing data, so they can only be tested forward, and Z2's
  mirror would pay the same high turnover.
- Z1 (weekend long) is a beta bet that pays in trending bull markets (TREND Sharpe 3.8 / 1.9) and not in chop or bear.
  It narrowly fails and adds almost nothing to the blend, which already holds trend.
- Crypto regimes again favour trend-type exposure; nothing here works in chop, consistent with the chop-regime search.
