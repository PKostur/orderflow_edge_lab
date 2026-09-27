# Multi-premia (trend + cross-sectional momentum + funding carry): result (all passed)

- Protocol: `multi-premia-v1`, declared in `c7b80d6`
- Evaluator fix `fix: weekly blend mask`: the evaluator crashed before any output, so no result was seen before the fix
- Universe: 70 crypto perps (point-in-time), 2020–2026, 20 bps, Binance funding proxy
- Status: descriptive

| Book | Sharpe | t | Annual return | Max drawdown | Halves (2020–23 / 2023–26) | Pass |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| S1 trend core | 1.23 | 2.87 | 14.6% | −10.2% | 1.49 / 0.96 | – |
| S2 cross-sectional momentum (frozen 30/7 rules) | 0.90 | 2.20 | 31.6% | −43.5% | 0.66 / 1.33 | yes |
| S3 cross-sectional funding carry (new) | 1.63 | 3.48 | 52.9% | −45.3% | 2.26 / 0.83 | yes |
| **S4 equal-risk blend** | **2.09** | **4.48** | 28.5% | **−14.1%** | **2.37 / 1.86** | **yes** |

Correlations: S1–S2 0.30, S1–S3 0.01, S2–S3 0.17.

## Robustness checks for carry

- The proxy holds: over 2025-04 to 2026-09, carry with real MEXC funding has
  Sharpe 0.72, against 0.70 with the Binance proxy.
- The edge is mostly price: price-only carry over 2020–26 has Sharpe 1.21
  (t 2.65). High-funding (crowded) coins underperform, and funding adds on
  top.
- Carry was weaker recently (Sharpe about 0.7 over 2025–26, not significant on
  its own).

## Reading

Three low-correlation premia combine into a book with Sharpe about 2 and a
drawdown shallower than either market-neutral leg alone. This is the best
result so far and comes from diversification, not tuning. Caveats: all data
is seen except S2's rules on the 53 coins; survivorship in the coin list; the
market-neutral legs have large standalone drawdowns (−44%) and short-squeeze
tail risk. Next: a forward registration of the S4 book.

## Robustness (declared in `multi-premia-robustness-v1`; not used for selection)

One dimension at a time around the frozen point:

| Varied | Values | Blend Sharpe |
| --- | --- | --- |
| XS momentum lookback | 14 / 30 / 60 days | 2.08 / 2.09 / 1.91 |
| Carry lookback | 3 / 7 / 14 days | 2.10 / 2.09 / 1.97 |
| Rebalance | 3 / 7 / 14 days | 1.88 / 2.09 / 1.60 |
| Quantile | 0.20 / 0.25 / 0.33 | 1.95 / 2.09 / 2.16 |

Every neighbour keeps the blend Sharpe at or above 1.6, and above trend alone
(1.23–1.25). Max drawdown ranges from −13% to −17%. The result is not a knife
edge. The weakest neighbour is 14-day rebalancing, which slows the
market-neutral legs.
