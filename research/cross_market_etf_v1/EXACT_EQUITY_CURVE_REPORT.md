# Exact equity-curve audit: filtered ETF candidates

This report supersedes rounded cumulative-return summaries for the historical July, August and September frozen windows.

Canonical windows:

* July development: 2026-07-06 through 2026-07-31.
* August locked holdout: 2026-08-03 through 2026-08-28.
* September confirmation: 2026-09-01 through 2026-09-16.
* August 31 is excluded from both locked windows.

All returns are after the frozen 2 bps round-trip friction.

## Portfolio model

Two views are retained:

1. Constant-notional cumulative return: sum every trade's net bps. This is the cleanest raw strategy PnL path.
2. Four-sleeve account equity: 25% of account capital assigned to each of SPY, QQQ, GLD and USO. An unused sleeve remains cash. Same-day ETF returns are aggregated and the account compounds daily.

## H1 ORB context v1

| Metric | Exact result |
|---|---:|
| Trades | 41 |
| Constant-notional cumulative return | +31.178 bps |
| Mean net return / trade | +0.760 bps |
| Win rate | 51.22% |
| Profit factor | 1.076 |
| Four-sleeve compounded account return | +0.0770% |
| Four-sleeve max drawdown | -0.5145% |

Period cumulative return:

| Window | Trades | Cumulative bps | EV / trade |
|---|---:|---:|---:|
| July | 18 | +147.968 | +8.220 |
| August | 16 | +19.331 | +1.208 |
| September | 7 | -136.120 | -19.446 |

The constant-notional curve reached approximately +237.347 bps on 2026-08-17 and finished at +31.178 bps. Roughly 87% of peak accumulated profit was surrendered.

Ticker net contribution over the full exact ledger:

* QQQ: +190.114 bps.
* GLD: -30.757 bps.
* SPY: -55.089 bps.
* USO: -73.090 bps.

QQQ contributes 47.4% of positive PnL and is the only ticker with positive net contribution. The largest single winner accounts for 13.8% of positive PnL and the top three winners for 36.9%.

Interpretation: the positive final endpoint hides a severe deterioration and cross-ticker weakness. H1 remains no-promotion.

## H2 VWAP reversion context v1

| Metric | Exact result |
|---|---:|
| Trades | 25 |
| Constant-notional cumulative return | +237.960 bps |
| Mean net return / trade | +9.518 bps |
| Win rate | 68.00% |
| Profit factor | 3.980 |
| Four-sleeve compounded account return | +0.5963% |
| Four-sleeve max drawdown | -0.0638% |
| Largest winner share of positive PnL | 16.59% |
| Top-three winners share of positive PnL | 43.86% |

Period cumulative return:

| Window | Trades | Cumulative bps | EV / trade |
|---|---:|---:|---:|
| July | 14 | +182.065 | +13.005 |
| August | 4 | +24.593 | +6.148 |
| September | 7 | +31.302 | +4.472 |

The constant-notional curve finishes at a new high of +237.960 bps. Its largest constant-notional drawdown is approximately 25.524 bps, occurring in early September before the curve recovered to a new high on 2026-09-15.

Ticker net contribution over the full exact ledger:

| Ticker | Trades | Net contribution bps | Share of positive PnL |
|---|---:|---:|---:|
| USO | 7 | +162.156 | 55.7% |
| QQQ | 8 | +45.441 | 23.6% |
| GLD | 4 | +34.895 | 15.6% |
| SPY | 6 | -4.531 | 5.1% |

The result remains meaningfully USO-heavy, but unlike H1 it is not a one-trade or one-ticker-only positive result. QQQ and GLD are also positive on a net basis.

## Audit correction

Earlier aggregate reporting accidentally allowed an August 31 H2 observation to contaminate the September label and also produced an inconsistent H1 September count. The exact ledgers above enforce the frozen date windows directly. Candidate definitions, factors, entries and exits were not changed.

## Research conclusion

Under the equity-curve-first framework:

* H1 fails the persistence test despite ending slightly positive overall. Its path is dominated by a large giveback and one positive ticker.
* H2 remains the historical survivor. Its cumulative path rises across July, August and September, drawdown is small under the declared account model, and the result is not dominated by one isolated trade.
* H2 remains prospective-shadow only. Historical cumulative return does not authorize live trading or leverage.
