# Residual Right-Tail Historical Replication v1

## Evidence status

Backward historical replication of the already-inspected rolling-beta-spread momentum candidate. This is an independent calendar period, but it is not prospective future-after-freeze OOS because the hypotheses and strategy were selected using later data.

Replication period: **2025-09-01 through 2026-03-01**.

Later development period for comparison: **2026-03-01 through 2026-09-12**.

All strategy parameters remained unchanged: 1h rolling-beta-spread momentum, regression window 192, |z| >= 1.5, hold 8 bars. No strategy threshold, exit, stop, cost, leverage or feature was optimized on the replication period.

## Frozen state replication

Protocol: `config/residual_right_tail_historical_replication_v1.json`.

The independent-period data produced **1,461 exact source signals**.

The state replication used only the small hypothesis set frozen before fetching the period:

- cross-sectional 4h breadth;
- BTC 4h trend and 24h/48h realized volatility;
- residual cross-sectional rank/dispersion;
- local 24h range state and 4h return;
- a compact combination of those features;
- residual-geometry baseline.

There were **36 total state epochs**: 18 continuous and 18 binary.

### Continuous target

**0/18** continuous epochs passed the replication gate.

The highest primary score came from a one-feature breadth model using HistGradientBoosting:

- median within-symbol chronological fold Spearman: **+0.0694**;
- positive full test folds: **3/5**;
- permutation null median: 0.000;
- permutation 95th percentile: approximately +0.085;
- 20,000-permutation p-value: **0.0879**.

This fails both the frozen 80% fold-stability requirement and p < 0.01 adversarial gate.

### Binary right-tail target

Only **1/18** binary epochs passed the raw chronological gate.

The frozen family winner was a two-feature local-state HistGradientBoosting model using 24h range state and 4h asset return:

- median within-symbol fold AUC: **0.5632**;
- AUC > 0.5 in **4/5** full folds;
- fold AUC medians approximately 0.611, 0.530, 0.563, 0.589, 0.390;
- permutation null median: 0.500;
- permutation 95th percentile: approximately 0.567;
- 20,000-permutation p-value: **0.0606**.

It therefore fails the adversarial replication gate.

### Feature-hypothesis replication

The later-period v1.1 marginal observations did not transfer strongly. In the earlier period:

- cross-sectional positive-return breadth fell from about +0.122 later-period cell rho to about **+0.037**;
- BTC 4h return fell from about +0.106 to about **+0.019**;
- BTC 24h realized volatility changed from about +0.105 to about **-0.042**;
- residual absolute cross-sectional rank was only about **+0.055**.

The strongest absolute earlier-period marginal association was rolling beta itself at approximately **-0.109**, with poor sign consistency across cells. The proposed explanation for the later right-tail winners therefore does not replicate as a stable market-state relationship.

## Frozen economic replication

Protocol: `config/rolling_beta_spread_historical_economic_replication_v1.json`.

The unchanged strategy was then evaluated without parameter search.

### Earlier-period economics

At 12 bps round-trip cost:

- mean net expectancy: **-0.31 bps/trade**;
- PF: **0.997**;
- positive folds: 5/9;
- positive symbols: 3/9.

At the primary 16 bps round-trip cost:

- trades: **1,461**;
- mean net expectancy: **-4.31 bps/trade**;
- median trade: **-16.0 bps**;
- PF: **0.956**;
- win rate: **45.7%**;
- median fold expectancy: +7.49 bps, but only **5/9** folds positive;
- positive symbols: **3/9**;
- 1%-each-tail trimmed mean: **-7.09 bps/trade**;
- best symbol: DOGE, approximately +16.30 bps/trade;
- worst symbol: LINK, approximately -18.80 bps/trade;
- best 21-day fold: approximately +39.16 bps/trade;
- worst fold: approximately -53.36 bps/trade.

At 20 bps:

- mean net expectancy: **-8.31 bps/trade**;
- PF: **0.916**.

The replication-period break-even cost is therefore only about **11.7 bps round trip**, below the repo's 16 bps primary assumption.

### Directional-regime reversal

The side decomposition is the strongest evidence against a stable directional mechanism.

Replication period, 16 bps:

- longs: **-25.98 bps/trade**;
- shorts: **+17.33 bps/trade**.

Later development period, 16 bps:

- longs: **+16.47 bps/trade**;
- shorts: **-10.82 bps/trade**.

The sign of the side advantage reverses across the two adjacent calendar periods. The later positive result therefore behaves like a regime-specific directional exposure rather than a stable residual-momentum edge.

## Leverage replication

The same earlier-period trades were replayed with 1x, 2x, 5x and 10x leverage. Costs scale with notional. Equal capital is split across nine symbol sleeves, matching the previous leverage diagnostic design.

At 16 bps:

| Leverage | Exact terminal equity | Max drawdown | Bootstrap median terminal | Bootstrap 5th pct | P(terminal < start) |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1x | **0.891x** | -25.2% | 0.915x | 0.698x | 71.0% |
| 2x | **0.724x** | -46.6% | 0.797x | 0.468x | 76.3% |
| 5x | **0.229x** | -85.9% | 0.354x | 0.087x | 90.0% |
| 10x | **0.006x** | -99.7% | 0.0147x | 0.00054x | 98.7% |

Each bootstrap uses **100,000 whole 21-day dependence-cluster epochs**, applying the same sampled calendar fold to all symbol sleeves.

At 10x, the raw compounded path already produces two non-positive trade factors; the optimistic reconstructed 1/leverage MAE bound flags seven adverse-path breaches. These are not exact MEXC liquidation thresholds.

Leverage again magnifies the underlying expectancy and path risk; it cannot stabilize this candidate.

## Descriptive full-span aggregation

For additional context only, concatenating the raw MEXC history continuously from 2025-09-01 through 2026-09-12 and replaying the same frozen strategy yields **3,148 exact trades**. This aggregate was not a predeclared promotion test.

At 16 bps:

- mean net expectancy: **-0.87 bps/trade**;
- PF: **0.990**;
- positive symbols: 4/9;
- 1x exact equal-sleeve terminal: **0.965x**;
- 2x terminal: **0.842x**;
- 5x terminal: **0.129x**;
- 10x terminal: approximately **0.00039x**.

At 12 bps the full-span mean is only about +3.13 bps/trade with PF 1.037; at 20 bps it is about -4.87 bps/trade with PF 0.945. The candidate is therefore strongly friction-sensitive even when both periods are aggregated.

## Conclusion

The strongest v2.1.3 performer does **not** survive independent calendar replication as a stable edge.

1. The proposed right-tail state explanation does not replicate under the frozen 36-epoch hypothesis test.
2. The fixed source strategy is negative in the independent earlier period at 12, 16 and 20 bps mean expectancy, with PF below 1 at all three cost cases.
3. The long/short advantage reverses sign between periods, directly contradicting a stable directional residual-momentum mechanism.
4. 2x, 5x and 10x leverage all worsen the independent-period compounded outcome; 10x is effectively destructive.
5. Across the continuous Sep-2025 to Sep-2026 span, the strategy is approximately break-even gross of small cost differences but negative at the primary 16 bps economics.

Research decision: **do not promote, leverage, or continue optimizing this rolling-beta-spread momentum cell as a primary candidate.** Preserve it as a documented regime-dependent phenomenon and shift strategy discovery to mechanisms with a larger and more stable gross payoff before leverage.

Claims remain: backward historical replication only, not prospective OOS; no profitable edge established; live execution disabled.
