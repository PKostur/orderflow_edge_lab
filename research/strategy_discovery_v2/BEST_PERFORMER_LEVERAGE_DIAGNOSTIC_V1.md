# Best-Performer Leverage Diagnostic v1

## Evidence status

This is a post-selection diagnostic of already-inspected strategy-discovery-v2.1.3 results. Candidate selection is outcome-dependent. Nothing here is untouched OOS evidence and nothing can auto-promote a strategy, enable live trading, or establish a profitable edge.

Source experiment: `strategy-discovery-v2.1.3-low-turnover`

Source workflow run: `34856870642`

Source head: `036b83d5a050b919e7a0046168edf3a2dbf9ab8b`

Diagnostic workflow run: `34860252045`

Diagnostic source head: `ba1817474578f84c00af79650f8201771a9d4a50`

The diagnostic regenerated the exact source trades from the archived v2.1.3 15m/1h MEXC data. It failed closed unless each selected strategy reproduced both the exact historical trade count and the exact 16 bps median-fold result.

## Candidate set

The frozen diagnostic set was the top five 1h rows from the v2.1.3 primary-cost economic leaderboard plus the best 15m row as a negative control.

| Candidate | Trades | Mean net bps | Median fold net bps | PF | Positive folds | Positive symbols |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1h rolling-beta-spread momentum, 192 / z1.5 / hold8 | 1,616 | +4.61 | +1.10 | 1.061 | 5/10 | 7/9 |
| 1h session-VWAP reversion, 1.5 / hold4 | 2,184 | -8.24 | -0.27 | 0.858 | 5/10 | 1/9 |
| 1h range-expansion fade, z1.5 / hold8 | 1,568 | -7.52 | -0.51 | 0.911 | 5/10 | 3/9 |
| 1h session-VWAP reversion, 1.5 / hold8 | 1,678 | -5.18 | -2.88 | 0.932 | 4/10 | 3/9 |
| 1h opening-range reversal, 4 / 0.25 ATR / hold8 | 2,828 | -9.68 | -3.34 | 0.870 | 3/10 | 2/9 |
| 15m range-expansion fade, z1.0 / hold8 control | 8,136 | -11.42 | -10.39 | 0.743 | 0/10 | 0/9 |

## Deep dive: rolling-beta-spread momentum

This remains the only selected row with positive 16 bps arithmetic expectancy, but its robustness is poor.

- Mean net expectancy: **+4.61 bps/trade**.
- Median trade: **-14.35 bps**.
- Win rate: **46.72%**.
- PF: **1.061**.
- Median fold expectancy: **+1.10 bps**, but only **5/10** folds are positive.
- Best symbol: **ENA +47.35 bps/trade**. Removing ENA changes overall mean expectancy to **-0.74 bps** and median-fold expectancy to **-4.28 bps**.
- Best 21-day fold: **+60.17 bps/trade**. Removing that fold changes overall mean expectancy to **-2.61 bps**.
- Worst fold: **-54.15 bps/trade**.
- Best 1% of trades, 16 trades, contribute roughly **275% of total net PnL**. Removing 1% from each tail changes mean expectancy from **+4.61 bps to -0.94 bps**.
- Long trades average **+16.47 bps** while short trades average **-10.82 bps**.
- The 96-bar regression neighbor was already negative at 12 bps, while the 192-bar cell turns negative at 20 bps. Parameter and friction stability are therefore weak.

Interpretation: the apparent edge is a right-tail, long-biased and regime-concentrated effect. It is not yet broad enough across time, symbols or neighboring parameters to freeze as a candidate.

## Leverage methodology

Requested leverage tests: **2x, 5x and 10x**. A 1x baseline was retained for comparison.

Leverage does not change entries, exits, trade signs, positive-fold fraction, positive-symbol fraction or PF. Gross PnL and trading costs both scale with notional. Leverage can therefore magnify an existing edge or loss but cannot manufacture one.

Portfolio replay uses nine equal-capital symbol sleeves. Each sleeve compounds only the exact source trades of its symbol. Because the source protocol allows at most one active trade per symbol, this preserves cross-symbol concurrency without pretending the whole account can be independently committed to every simultaneous trade.

For path risk, MAE is reconstructed from the underlying high/low bars between entry and exit. An underlying adverse move of `-1/leverage` is treated only as an optimistic pre-maintenance capital-wipeout bound. It is **not** labeled as an exact MEXC liquidation threshold because historical maintenance-margin tiers and liquidation mechanics were not frozen in the source experiment.

## Leverage results: top rolling-beta-spread cell

| Leverage | Exact terminal equity | Exit-marked max DD | MAE bound breaches | Bootstrap median terminal | Bootstrap 5th pct | P(terminal < start) | P(terminal < 0.5x) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1x | 1.098x | -13.5% | 0 | 1.115x | 0.814x | 29.4% | 0.0% |
| 2x | **1.184x** | **-25.4%** | 0 | **1.251x** | **0.660x** | **29.5%** | **0.6%** |
| 5x | 0.818x | -54.5% | 0 | 1.224x | 0.285x | 42.4% | 17.7% |
| 10x | 0.142x | -90.8% | 3 raw trade MAE breaches | 0.404x | 0.041x | 68.6% | 54.9% |

The exact historical path peaks around the low-single-digit leverage range, not at 5x or 10x. The requested grid shows **2x is the only tested leverage that improves the realized historical terminal value without severe volatility drag**. This is not a recommendation to trade at 2x; it is a diagnostic result on post-selected historical data.

The 5x case is especially informative: arithmetic expectancy scales upward, but realized compounded terminal equity falls below the starting value because the return distribution is too volatile and negatively skewed around a small mean. At 10x, path risk dominates completely.

## Other selected strategies under leverage

All other selected strategies had negative unlevered 16 bps expectancy. Leverage magnified those losses rather than rescuing them.

| Candidate | 2x exact terminal | 5x exact terminal | 10x exact terminal | 10x MAE-bound trade breaches |
| --- | ---: | ---: | ---: | ---: |
| 1h VWAP reversion 1.5 / hold4 | 0.605x | 0.175x | 0.0047x | 7 |
| 1h range-expansion fade 1.5 / hold8 | 0.688x | 0.263x | 0.028x | 11 |
| 1h VWAP reversion 1.5 / hold8 | 0.792x | 0.469x | 0.109x | 15 |
| 1h opening-range reversal 4 / 0.25 / hold8 | 0.496x | 0.108x | 0.0011x | 18 |
| 15m range-expansion fade control | 0.110x | 0.0019x | effectively 0x | 5 |

## Bootstrap design

Each candidate/leverage case uses **100,000 bootstrap epochs**. Each epoch resamples whole 21-day dependence clusters with replacement and applies the same sampled cluster to every symbol sleeve, preserving the calendar dependence structure and cross-symbol co-movement better than trade-level resampling.

There are six candidates and four leverage levels, with both exit-only and MAE-bound bootstrap views, for **4.8 million 100,000-epoch candidate/leverage/path evaluations** in aggregate. At 100,000 epochs the worst-case Monte Carlo standard error for a probability estimate is about 0.16 percentage points.

## Conclusion

The leverage test does not change the research verdict.

1. **No selected strategy is promotable.** The source v2.1.3 primary economic gate still has zero passes.
2. The rolling-beta-spread momentum cell is worth understanding further because it is the only near-positive economic row, but it is tail-dependent, ENA-dependent, fold-dependent, long-biased, parameter-fragile and cost-sensitive.
3. **2x is the only requested leverage that survives the historical replay reasonably well.** 5x already suffers strong volatility drag and 10x is incompatible with the observed path risk.
4. Leverage must remain downstream of edge validation. It cannot be used to rescue negative or unstable expectancy.
5. The next research step should explain the top cell's state dependence before any new PnL optimization: which volatility, BTC, residual-dispersion, session and liquidity states precede the large right-tail winners, and whether those states predict directionality independently of strategy PnL. Any such feature work must be predeclared and state-first.

Claims remain: development diagnostic only, no verified OOS, no profitable edge established, no live execution.
