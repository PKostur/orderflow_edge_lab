# OCC Strategy R5.1 External Outlier Results

Status: external outlier only. OCC R5.1 was not added to the candidate registry, candidate selection, shadow execution, or live execution paths. No parameter search was performed.

## Frozen implementation

The study used the published default structure: SMMA length 8, alternate-resolution multiplier 3x, both long and short directions, no stop loss, no take profit, and next-chart-bar-open fills after a crossover signal. Seven days of prehistory initialized indicators, but only trades inside each scored window were included.

Three variants were compared:

1. `original_lookahead`, a deliberately biased diagnostic reproduction of the historical higher-timeframe lookahead behavior.
2. `confirmed_htf`, the causal version that can only use the last fully completed higher-timeframe candle.
3. `same_tf`, a same-timeframe open/close SMMA crossover control.

Universe: BTC_USDT, ETH_USDT, SOL_USDT, XRP_USDT, DOGE_USDT, LINK_USDT, SUI_USDT, ENA_USDT on 5m, 15m, and 1h, giving 24 symbol/timeframe cells per variant.

## Window A: 2026-06-01 through 2026-09-12

At zero trading costs:

| Variant | Median expectancy, bps/trade | Median PF | Positive cells | Trades |
| --- | ---: | ---: | ---: | ---: |
| Original lookahead | +71.29 | 12.89 | 24/24 | 18,632 |
| Confirmed HTF | -2.24 | 0.894 | 9/24 | 18,640 |
| Same timeframe | -2.07 | 0.890 | 3/24 | 55,330 |

At 16 bps round-trip friction:

| Variant | Median net expectancy, bps/trade | Median PF | Positive cells |
| --- | ---: | ---: | ---: |
| Original lookahead | +55.29 | 5.98 | 24/24 |
| Confirmed HTF | -18.24 | 0.593 | 1/24 |
| Same timeframe | -18.07 | 0.437 | 0/24 |

The paired median expectancy gap between the lookahead reproduction and causal confirmed-HTF implementation was about 76.30 bps per trade.

The only causal cell still positive at 16 bps was LINK_USDT 1h: 137 trades, +6.31 bps arithmetic net expectancy per trade, PF 1.088, compounded return +3.56%, max drawdown -30.58%. It was unstable by month and was driven by the long side. LINK 1h long returned +26.71 bps/trade net at 16 bps, while LINK 1h short returned -14.39 bps/trade.

Across all eight symbols, the causal 1h version had +3.89 bps/trade gross before costs, but -12.11 bps/trade after 16 bps friction. Its gross long side was +24.50 bps/trade while its gross short side was -16.96 bps/trade. The 5m and 15m causal versions were negative even before costs.

## Window B: retrospective replication, 2026-03-01 through 2026-06-01

This window was frozen after Window A had been inspected. It is therefore retrospective replication, not genuine future out-of-sample evidence. The full universe and all three timeframes were retained without selecting the later winners.

At zero trading costs:

| Variant | Median expectancy, bps/trade | Median PF | Positive cells | Trades |
| --- | ---: | ---: | ---: | ---: |
| Original lookahead | +76.87 | 14.30 | 24/24 | 15,997 |
| Confirmed HTF | -1.88 | 0.924 | 5/24 | 15,987 |
| Same timeframe | -0.43 | 0.967 | 7/24 | 48,118 |

At 16 bps round-trip friction:

| Variant | Median net expectancy, bps/trade | Median PF | Positive cells |
| --- | ---: | ---: | ---: |
| Original lookahead | +60.87 | 7.29 | 24/24 |
| Confirmed HTF | -17.88 | 0.585 | 1/24 |
| Same timeframe | -16.43 | 0.482 | 0/24 |

The paired median expectancy gap between the lookahead reproduction and causal implementation was about 80.54 bps per trade.

The sole positive causal cell at 16 bps was ENA_USDT 1h: 118 trades and +1.25 bps arithmetic net expectancy per trade, but PF 1.010, compounded return -8.94%, and max drawdown -39.27%.

Across all eight symbols, causal 1h OCC was already negative before costs in this earlier window: -11.25 bps/trade gross, PF 0.858. The 1h long side was -7.76 bps/trade gross and the short side was -14.74 bps/trade gross. At 16 bps friction, pooled 1h expectancy was -27.25 bps/trade.

## Interpretation

The very strong TradingView-style profitability did not survive removal of the higher-timeframe lookahead behavior. The lookahead reproduction was positive in every one of 24 cells in both windows, whereas the causal implementation was negative at the median before costs in both windows and strongly negative after realistic friction.

The later-period 1h long pocket does not replicate as a broad OCC effect in the earlier period. The identity of the lone 16-bps survivor changed from LINK 1h in Window A to ENA 1h in Window B, and pooled 1h long expectancy changed from strongly positive gross in Window A to negative gross in Window B. This is more consistent with period-specific directional conditions than with a stable cross-symbol OCC long/short edge.

No promotion decision is attached to this study. OCC remains an external anomaly record only.