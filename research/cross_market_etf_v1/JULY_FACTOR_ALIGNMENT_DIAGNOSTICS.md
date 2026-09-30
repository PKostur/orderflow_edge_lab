# ETF July factor-alignment diagnostics

This is exploratory development analysis using July only. It does not overwrite the original frozen D0 audit record, and August remains uninspected.

Goal: identify pre-entry context that explains why some H1 and H2 signals travel farther after entry.

Only information available at or before the signal timestamp is used.

## H1 ORB15 continuation

Base July behavior:

* 76 signals.
* Directional win rate: 53.95%.
* Net expectancy after 2 bps friction: +1.265 bps/trade.
* Average MFE: 21.83 bps.
* Average MFE when fixed-exit direction is correct: 31.69 bps.

### Factor screen

The strongest monotonic development relationships were:

1. Breakout depth beyond the opening-range boundary.
2. Five-minute momentum in the breakout direction.
3. Price displacement from cumulative VWAP in the breakout direction.
4. Relative signal-minute volume.

Absolute-threshold quartile screen:

| Alignment score | N | Net win rate | EV bps | MFE bps | MAE bps |
|---:|---:|---:|---:|---:|---:|
| 0 | 12 | 25.00% | -6.206 | 7.806 | 20.025 |
| 1 | 17 | 47.06% | -1.250 | 17.613 | 16.868 |
| 2 | 18 | 44.44% | -0.355 | 24.732 | 20.457 |
| 3 | 19 | 57.89% | +5.650 | 24.979 | 18.442 |
| 4 | 10 | 60.00% | +9.088 | 34.636 | 23.584 |

Because absolute bps thresholds can simply select higher-volatility ETFs, a second screen ranked each factor within ticker.

Ticker-normalized factor-alignment screen:

| Alignment score | N | Net win rate | EV bps | MFE bps | MAE bps |
|---:|---:|---:|---:|---:|---:|
| 0 | 8 | 12.50% | -13.752 | 8.537 | 28.650 |
| 1 | 16 | 43.75% | -1.059 | 16.337 | 14.965 |
| 2 | 33 | 51.52% | +0.413 | 24.317 | 21.815 |
| 3 | 14 | 57.14% | +9.357 | 25.805 | 15.846 |
| 4 | 5 | 60.00% | +15.700 | 33.163 | 14.222 |

This preserves a strong monotonic relationship after removing much of the cross-ticker volatility bias.

### Slower context

Within-ticker quartiles:

* Five-minute momentum is the cleanest continuation factor.
  * Bottom quartile: 25.0% wins, -10.24 bps EV, 13.82 bps MFE.
  * Third quartile: 57.9% wins, +8.42 bps EV, 25.44 bps MFE.
  * Top quartile: 52.9% wins, +7.87 bps EV, 29.71 bps MFE.
* Fifteen-minute momentum is less monotonic but its top quartile reaches 28.14 bps MFE and +5.28 bps EV.
* Extreme same-direction opening-gap alignment does not help.
  * Top gap-alignment quartile: 35.3% wins and -6.28 bps EV.
* Open-to-signal trend is not independently monotonic.

Development interpretation:

The best H1 state is not simply "the strongest trend day." It looks more like a decisive opening-range escape with fresh local momentum, VWAP alignment, and participation. Extremely pre-extended days can be worse.

### Ticker spread for ticker-normalized score >= 3

| Ticker | N | Win rate | EV bps | MFE bps |
|---|---:|---:|---:|---:|
| GLD | 5 | 40.0% | +1.14 | 17.63 |
| QQQ | 3 | 100.0% | +45.77 | 53.93 |
| SPY | 5 | 40.0% | -5.54 | 11.84 |
| USO | 6 | 66.7% | +15.69 | 36.33 |

Caution: sample sizes are small, and SPY does not benefit in July. This is a reason to continue development, not a reason to ticker-filter post hoc.

## H2 VWAP-volatility reversion

Base July behavior:

* 75 signals.
* Directional win rate: 53.33%.
* Net expectancy after 2 bps friction: +1.837 bps/trade.
* Average MFE: 19.65 bps.
* Average MFE when fixed-exit direction is correct: 24.86 bps.

### Factor screen

The clearest monotonic factors were:

1. Larger displacement from cumulative VWAP.
2. Larger signal candle range.
3. Higher relative signal-minute volume.

Within-ticker normalized three-factor screen:

| Number of aligned factors | N | Net win rate | EV bps | MFE bps | MAE bps |
|---:|---:|---:|---:|---:|---:|
| 0 | 19 | 47.37% | +2.348 | 15.450 | 10.056 |
| 1 | 22 | 40.91% | -0.401 | 15.253 | 16.212 |
| 2 | 19 | 31.58% | -3.484 | 24.598 | 14.892 |
| 3 | 15 | 60.00% | +11.211 | 25.173 | 14.489 |

The full three-factor alignment is substantially better than the base H2 sample, but the score is not monotonic before all three align. Therefore this should be interpreted as a possible interaction, not a generic additive quality score.

### Slower extension context

Fifteen-minute extension before the signal shows an inverted-U shape:

| Extension quartile | N | Win rate | EV bps | MFE bps |
|---:|---:|---:|---:|---:|
| 1 | 20 | 20.0% | -3.04 | 12.76 |
| 2 | 20 | 75.0% | +9.71 | 22.08 |
| 3 | 19 | 47.4% | +4.39 | 19.36 |
| 4 | 16 | 31.3% | -4.94 | 25.59 |

This suggests the setup needs genuine displacement, but extreme extension can turn into continuation rather than reversion.

However, among the 15 trades where VWAP displacement, signal range, and relative volume all ranked in the upper half for that ticker, the most extended quartile still remained positive. Therefore the extension rule should not yet be hard-coded.

### Ticker spread for all three normalized participation/displacement factors aligned

| Ticker | N | Win rate | EV bps | MFE bps |
|---|---:|---:|---:|---:|
| GLD | 3 | 100.0% | +17.58 | 27.76 |
| QQQ | 5 | 60.0% | +9.90 | 26.35 |
| SPY | 3 | 33.3% | -3.05 | 10.40 |
| USO | 4 | 50.0% | +18.77 | 32.84 |

Again, SPY is weak and sample sizes are small. No ticker-specific exclusion is justified from July alone.

## Current development hypotheses

### H1 context hypothesis

A continuation breakout is more likely to produce larger favorable travel when several of these are present before entry:

* breakout is meaningfully beyond the opening-range boundary;
* recent five-minute momentum agrees with the breakout;
* price is displaced from VWAP in the breakout direction;
* signal-minute volume is high relative to the session context.

The relationship survives within-ticker normalization and is the strongest factor pattern found so far.

### H2 context hypothesis

A VWAP-reversion signal appears more useful when:

* displacement from VWAP is relatively large for that ticker;
* the signal candle range is relatively large;
* signal-minute volume is elevated.

This may represent a high-participation overextension state. Slow extension appears nonlinear and should remain diagnostic rather than a rule for now.

## Research discipline

These factor relationships are development findings from the same July sample used to discover them.

They are not validation evidence.

Next steps before August:

1. Define factors in a live-computable form that does not depend on knowing the full July distribution.
2. Replace retrospective within-ticker quartiles with rolling pre-signal percentiles or volatility-normalized values.
3. Examine time-to-MFE and time-to-MAE for the stronger H1 and H2 states.
4. Design a simple context filter plus stop/target/exit.
5. Freeze the resulting candidate.
6. Only then inspect August once.
