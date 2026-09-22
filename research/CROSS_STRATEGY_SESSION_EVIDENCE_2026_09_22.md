# Cross-strategy session evidence - 2026-09-22

Status: **exploratory observational session attribution, no strategy retuning**

This report expands session analysis beyond ENA. It uses the latest successful forward-shadow artifacts available on 2026-09-22 and preserves every strategy's existing frozen decision logic.

## Strategy set

Primary multi-coin strategies inspected:

1. `mexc_8h_ema24_96_atr025_v1` - base 8h EMA/ATR trend.
2. `mexc_8h_ema24_96_atr025_fibcore_v1` - Fibonacci-gated 8h trend.
3. `mexc_8h_ema24_96_atr025_markov_ev_v1` - Markov EV veto clone of the base trend.
4. `mexc_xs_mom30_7_dn_v1` - 30d/7d dollar-neutral cross-sectional momentum.

The DV2 payoff-meta shadow already has a dedicated lower-timeframe session-attribution implementation on branch `research/dv2-payoff-session-metrics-v1`. Gold also has dedicated session/state branches and is tracked separately because those studies are state research rather than currently executable PnL candidates.

## Fixed 8h portfolio windows

For 8h strategies, the portfolio bars naturally partition UTC time into:

* `00:00-08:00`: Asia-like crypto window.
* `08:00-16:00`: London plus London/New-York overlap.
* `16:00-24:00`: New-York post-overlap plus late transition.

These are deliberately called **coarse UTC portfolio windows**, not pure named exchange sessions.

Current mark-to-market intervals are excluded from the completed-window summaries below.

## Base 8h EMA/ATR trend

Latest forward snapshot: 28 completed/marked intervals, +16.1% reported net return, 3 completed symbol trades. The formal 20-completed-trade edge-review threshold has not been reached.

| UTC window | Completed intervals | Cumulative net | Mean net | Median net | Win rate | PF |
|---|---:|---:|---:|---:|---:|---:|
| 00-08 | 9 | +142.63 bps | +15.85 | +58.63 | 55.6% | 1.23 |
| 08-16 | 9 | **+1,005.41 bps** | **+111.71** | +49.16 | 66.7% | **8.54** |
| 16-24 | 9 | +286.89 bps | +31.88 | +24.75 | 55.6% | 1.87 |

The 08-16 window is the dominant contributor. Its largest positive interval contributed about 39.5% of positive PnL in that bucket, so the result is not a one-interval endpoint, although the sample is only nine completed windows.

## Fibonacci-gated 8h trend

Latest forward snapshot: 26 completed/marked intervals, +13.4% reported net return, zero completed symbol trades and two open positions. Formal edge review is therefore far away.

| UTC window | Completed intervals | Cumulative net | Mean net | Median net | Win rate | PF |
|---|---:|---:|---:|---:|---:|---:|
| 00-08 | 9 | +76.68 bps | +8.52 | +1.06 | 55.6% | 1.15 |
| 08-16 | 8 | **+899.66 bps** | **+112.46** | **+72.44** | **87.5%** | **15.81** |
| 16-24 | 8 | +130.32 bps | +16.29 | +61.67 | 75.0% | 1.24 |

Again, 08-16 is the dominant block. The largest positive 08-16 interval contributed about 44.1% of positive PnL in that bucket.

The Fibonacci strategy is derived from the same base trend family, so agreement between these two strategies is **not independent replication**. It is still useful because the entry gate changes exposure materially while preserving the same session ordering.

## Markov EV veto clone of 8h trend

Latest snapshot: +1.32% reported net return, 1 passed fresh entry and 12 vetoes. Exposure is much smaller than the base candidate.

| UTC window | Completed intervals | Cumulative net | Mean net | Median net | Win rate | PF |
|---|---:|---:|---:|---:|---:|---:|
| 00-08 | 7 | -33.81 bps | -4.83 | 0.00 | 28.6% | 0.38 |
| 08-16 | 6 | **+106.22 bps** | **+17.70** | +12.04 | 50.0% | no losing active interval |
| 16-24 | 6 | +42.30 bps | +7.05 | +2.85 | 66.7% | no losing active interval |

Despite the veto logic, the same ordering remains: 08-16 strongest, 16-24 second, 00-08 weakest. Again, this clone shares lineage and underlying signals with the base candidate, so it is supporting evidence rather than independent replication.

## 30d/7d cross-sectional momentum

The daily strategy cannot be classified by entry session because every rebalance occurs at the UTC daily boundary. Instead, its daily price PnL was decomposed into the same three 8h windows using the available MEXC 8h bars and the frozen portfolio weights.

This reconstruction exactly matches the daily **gross price** return when the three windows are added. Transaction costs are deliberately not assigned to a session. Funding requires lower-timeframe event attribution and is kept separate until the automated implementation is added.

Eight completed daily holding intervals were reconstructable:

| UTC window | Days | Cumulative gross price contribution | Mean/day | Positive days | PF |
|---|---:|---:|---:|---:|---:|
| 00-08 | 8 | **+252.38 bps** | +31.55 bps | 87.5% | 2.96 |
| 08-16 | 8 | -1.87 bps | -0.23 bps | 50.0% | 0.99 |
| 16-24 | 8 | **-261.36 bps** | -32.67 bps | 37.5% | 0.27 |

This is the opposite session shape from the 8h trend family.

However, the apparent Asia contribution is highly concentrated. September 19 contributed about +252.48 bps in 00-08. Removing that single day leaves the remaining 00-08 cumulative gross contribution approximately flat.

Therefore there is **no Asia filter conclusion** for cross-sectional momentum. The useful observation is that the daily strategy's recent losses have accrued disproportionately in 16-24 UTC, while its recent gains were concentrated in one Asia-window episode.

## Cross-strategy conclusion

The current evidence does not support one universal "best session."

Instead it suggests strategy-mechanism interaction:

* Trend-following portfolios currently show their strongest realized forward contribution in 08-16 UTC.
* The Markov-veto trend clone preserves the same ordering under much lower exposure.
* Cross-sectional momentum currently has a different shape: 00-08 positive, 08-16 flat, 16-24 negative, but the 00-08 gain is dominated by one day.
* Short-horizon ENA order-flow work found higher movement in London/New-York but weak broad directional expectancy, with only narrow exploratory substates looking positive.
* DV2 daily payoff-meta already uses additive intraday session attribution rather than entry-session labeling.
* Gold has a separate cross-session state research lane and should not be mixed mechanically with crypto-session economics.

The next research question is therefore not "which session is best?" It is:

> Which strategy mechanisms consistently earn or lose PnL in each session, and does that session contribution persist across future independent periods and symbols?

## Implementation

A generic `orderflow-portfolio-session-report` tool now computes cumulative net return, mean/median return, win rate, profit factor, max drawdown, concentration and the cumulative path for completed 8h portfolio intervals.

It is wired into:

* HTF trend forward shadow.
* HTF Fibonacci forward shadow.
* Markov EV shadow.

The cross-sectional daily strategy is now wired to fetch 8h bars and emit additive price+funding session attribution on each forward run. Rebalance transaction costs remain separate rather than being arbitrarily assigned to a session. The existing DV2 1h attribution remains the finer-grained model for future expansion.

No current candidate is modified. Any future session-conditioned execution rule requires a new candidate ID and a freeze before later evidence is inspected.
