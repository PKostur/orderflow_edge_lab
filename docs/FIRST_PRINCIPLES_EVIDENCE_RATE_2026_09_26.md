# Evidence rate from first principles (2026-09-26)

The binding constraint on this program is not code. It is how fast the
evidence can answer whether there is an edge. All figures below are same-period
history (2024-01-01 to 2026-09-12, 20 bps, already inspected) and are not
out-of-sample.

## 1. Detectability

Detecting an annualized Sharpe `S` at t ≈ 2 needs about `365 · (2/S)²` days.

| Object | Sharpe | t over 2.7 years | Forward days to t = 2 |
| --- | ---: | ---: | ---: |
| DON8 / EMA8 / VOL8, each alone (daily, before costs) | 0.75–0.83 | – | ~2,100–2,600 |
| Combined 30-sleeve portfolio, v3, net (plain) | 1.07 | 1.71 | ~1,275 |
| Same, beta-hedged | 1.07 | 1.66 | ~1,275 |
| Equal-weight buy-and-hold basket | 0.48 | 0.79 | – |

Per-trade scoring is worse still: per-trade Sharpe is 0.03–0.11, which needs
350–3,900 trades, and those trades cluster in time. Even in-sample, the
combined portfolio is not significant.

## 2. Breadth (participation ratio of correlation eigenvalues)

| Set | Effective N | Mean pairwise correlation |
| --- | ---: | ---: |
| 10 coins, buy and hold | 2.0 / 10 | 0.68 |
| 10 coins + 12 liquid alt perps (chosen by market-cap convention, not returns) | 2.6 / 22 | – |
| 3 strategy portfolios | 1.5 / 3 | 0.67 |
| 10 per-coin trend portfolios | 4.1 / 10 | 0.39 |
| 30 strategy × coin sleeves | 7.4 / 30 | 0.30 |

Marginal effective-N gain from adding one candidate: PAXG +0.35 (mean |corr|
to base 0.14), TRX +0.33 (0.21); every other alt adds ≤ 0.12, and AVAX −0.02.

## 3. Consequences

1. The strategies are not disguised crypto beta. Beta to the basket is about
   −0.1 to −0.2 per strategy and −0.04 for the portfolio, so a beta hedge adds
   nothing.
2. The three strategies are mostly one bet. Adding more trend variants on the
   same coins cannot speed up learning, and every extra variant spends
   multiple-testing budget.
3. More crypto coins add almost no breadth. Breadth must come from assets
   outside the crypto factor, meaning cross-asset trend following, where the
   trend premium also has the most independent prior evidence.
4. Score the portfolio on daily P&L, not per-trade cells. This is
   `universal-trend-portfolio-forward-v1` (start 2026-09-28).
5. Freeze further per-trade diagnostic studies on these three strategies. They
   cannot change the answer within any useful horizon.

## 4. Next candidate (not yet registered)

A cross-asset universe chosen before looking at any strategy P&L, and screened
only on data availability, liquidity and correlation to the crypto factor. It
would run the same frozen trend rules and the same daily-P&L protocol. The
target is effective N ≥ 6 at the asset level, which would cut the detection
horizon by roughly √(6/2) ≈ 1.7×.
