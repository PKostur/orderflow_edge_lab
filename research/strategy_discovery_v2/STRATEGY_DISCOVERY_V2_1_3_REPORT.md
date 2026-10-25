# Strategy Discovery v2.1.3: Low-Turnover Development Conclusion

## Status

Development screening only. No profitable-edge claim. No untouched out-of-sample claim. Live order transmission remains disabled.

This report records the admissible `strategy-discovery-v2.1.3-low-turnover` run on exact research head `036b83d5a050b919e7a0046168edf3a2dbf9ab8b` (GitHub Actions run `34856870642`). The protocol guard, immutable MEXC data preparation, 15m and 1h evaluation jobs, aggregate job, and deterministic multi-agent release-manager gate all completed successfully.

Superseded v2.1, v2.1.1, and v2.1.2 result artifacts are excluded from evidence. v2.1.1-v2.1.3 were outcome-blind reliability/validity amendments only: same-fold causal exits, actual-exit non-overlap, finite PF serialization, exit-fold index alignment, and enforcement of the already-frozen minimum eight-symbol breadth gate. Families, grids, symbols, dates, costs, and economic thresholds were not changed in response to results.

## Frozen experiment

- Public MEXC Futures klines, 2026-03-01 through 2026-09-12 exclusive.
- Context universe: BTC plus nine conditioning symbols (ETH, SOL, XRP, DOGE, BNB, ADA, LINK, SUI, ENA).
- Intervals: 15m and 1h.
- Dependence cluster: 21-day calendar fold; 10 usable folds in both interval reports.
- State prediction before PnL.
- Signal on completed bar t; entry at next bar open; fixed causal exit after the frozen hold; exit must remain inside the signal fold.
- Minimum symbol breadth: eight; all leading state/economic rows reported nine-symbol breadth.
- Round-trip cost cases: 12, 16, and 20 bps; 16 bps is the frozen primary case.
- Original-versus-reversed direction control retained.
- No best-cell auto-promotion.

## State prediction results

The state layer is substantially stronger than the earlier 15-300 second lane and is coherent across two timeframes.

| Interval | Frozen state trials | State passes | Pass fraction |
|---|---:|---:|---:|
| 15m | 112 | 56 | 50.0% |
| 1h | 112 | 44 | 39.3% |

The strongest 1h state result was `session_vwap_reversion`, threshold 1.5 and 8-bar horizon: median 21-day-fold Spearman `+0.1842`, 10/10 positive folds, nine-symbol breadth, and 5,390 eligible observations. The corresponding 15m configuration also led its interval: median Spearman `+0.1177`, 10/10 positive folds, nine-symbol breadth, and 71,354 eligible observations.

The family-level pattern is more important than any single parameter cell. On 1h, all tested variants of volume-shock reversal (8/8), opening-range reversal (8/8), session-VWAP reversion (4/4), and range-expansion fade (4/4) pass the state gate. On 15m, all tested variants of beta-residual reversion (16/16), volume-shock reversal (8/8), opening-range reversal (8/8), rolling-beta-spread reversion (8/8), BTC-relative-strength reversion (8/8), session-VWAP reversion (4/4), and range-expansion fade (4/4) pass.

Their continuation/momentum mirrors are mostly rejected or carry the opposite state association. This supports a broad development conclusion: over this historical MEXC window, the tested 15m/1h public-data state space is predominantly mean-reverting rather than continuation-dominant. This is predictive-state evidence, not trading-edge evidence.

## Costed strategy translation

Only state-pass variants were translated into costed trading results. Across the two intervals this produced 300 retained cost cases (132 on 1h and 168 on 15m). There were zero economic passes at the frozen 16 bps primary case.

The strongest 15m primary-cost row was `range_expansion_fade` (`range_z=1.0`, hold 8): 8,136 trades, nine-symbol breadth, median fold net expectancy `-10.3905 bps/trade`, median PF `0.7292`, zero positive net folds, and zero positive symbols. The original direction still beat its reversed control, but the absolute economics are decisively negative.

The strongest 1h primary-cost row was the more unusual `rolling_beta_spread_momentum` (`regression_window=192`, `threshold_z=1.5`, hold 8): 1,616 trades, nine-symbol breadth, median fold net expectancy `+1.0979 bps/trade`, median PF `1.0026`, and seven of nine symbols positive. It nevertheless has only 5/10 positive calendar folds, below the frozen 60% requirement, so `economic_pass=false`.

That 1h cell is also execution-cost and parameter-neighborhood sensitive. At 12 bps it records `+5.0979 bps` median fold net, PF `1.061`, 6/10 positive folds, and 7/9 positive symbols. At 20 bps it falls to `-2.9021 bps`, PF `0.948`, 5/10 positive folds, and 5/9 positive symbols. The neighboring 96-bar regression version is already negative at 12 bps (`-0.3943 bps`) and materially negative at 16 bps (`-4.3943 bps`). Therefore it is not a stable parameter neighborhood and must not be frozen by choosing the best in-sample regression window.

Other 1h rows that turn slightly positive at the 12 bps floor do not satisfy breadth/stability requirements. For example, session-VWAP reversion (`threshold=1.5`, hold 4) is `+3.73 bps` at 12 bps but only 2/9 symbols are positive; range-expansion fade (`range_z=1.5`, hold 8) is `+3.49 bps` but only 5/9 symbols are positive. These do not justify promotion.

## Interpretation

The low-turnover experiment improved the research picture without establishing a strategy edge:

1. There is repeated, broad 15m/1h mean-reversion state structure across nine conditioning symbols and ten independent calendar folds.
2. Moving from seconds to hours materially improves gross payoff scale versus the short-horizon lane.
3. Realistic execution economics still eliminate the 15m candidates.
4. One 1h rolling-beta-spread momentum cell reaches slightly positive median net at 16 bps but fails calendar-fold stability and parameter-neighborhood stability. It is a mechanistic lead only, not a candidate.
5. The current BTC-relative and beta-spread strategies are single-leg futures signals conditioned on BTC. They are not a true beta-hedged two-leg portfolio and must not be described as validated statistical arbitrage or institutional relative-value alpha.

Because no row passes the frozen primary economic screen, no MAE/MFE stop ladder, candidate freeze, paper-shadow promotion, or live-execution step is triggered.

## Next research lane

A genuinely different next protocol may test true hedged relative-value mechanics rather than simply tuning the winning-looking cell. It should be predeclared as a new development trial family, include both legs, rolling hedge ratio, two-leg fees/slippage, legitimate funding cash flows, rebalancing turnover, stationarity/mean-reversion diagnostics where claimed, and the same calendar dependence clusters and reversed/placebo controls. Any design informed by this report is post-development and therefore cannot use this same 2026-03-01 to 2026-09-12 window as untouched validation.

A second orthogonal lane can examine low-turnover session/seasonality and derivatives carry/funding using only fields genuinely available from public MEXC or existing licensed feeds. Future-after-freeze evidence remains mandatory before any profitable-edge claim.
