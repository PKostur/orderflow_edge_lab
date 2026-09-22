# ETF July development diagnostics

This note does not overwrite the frozen D0 results in `D0_RESULTS.json`. Those remain an audit record of the original protocol.

The testing workflow is now separated into two phases:

1. Development diagnostics first.
2. Candidate freeze and locked validation only after the signal and exit geometry are understood.

## Development metrics

Primary diagnostics:

* Directional win rate at the defined exit.
* Net win rate after frozen round-trip friction.
* Average net winner.
* Average net loser.
* Net expectancy per trade.
* Maximum favorable excursion (MFE).
* Maximum adverse excursion (MAE).
* MFE conditional on the eventual direction being correct.
* Fraction of available favorable movement captured by the fixed exit.
* Target-hit rates for practical excursion thresholds.

No August data was used.

## H1 ORB15 continuation

* Signals: 76
* Directional win rate: 53.95%
* Net win rate after 2 bps friction: 47.37%
* Average net win: +20.5412 bps
* Average net loss: -16.0835 bps
* Net expectancy: +1.2650 bps/trade
* Approximate break-even win rate from average win/loss: 43.91%
* Approximate profit factor from average win/loss and realized net win rate: 1.15
* Average MFE across all trades: 21.8322 bps
* Average MAE across all trades: 19.4934 bps
* Average MFE when fixed-exit direction is correct: 31.6896 bps
* Average realized gross return when direction is correct: 19.9105 bps
* Average fixed-exit capture of winner MFE: 60.63%
* Winner MAE: 12.674 bps
* Loser MFE: 10.285 bps
* Loser MAE: 27.481 bps
* Hit +10 bps favorable excursion: 69.74%
* Hit +15 bps: 57.89%
* Hit +20 bps: 47.37%
* Hit +25 bps: 38.16%
* Hit +30 bps: 28.95%
* Hit +35 bps: 21.05%
* Hit +40 bps: 17.11%

Development interpretation: signal remains worth studying. Winner and loser excursion geometry is meaningfully different, and the fixed 15-minute exit leaves favorable movement uncaptured.

## H2 VWAP-volatility reversion

* Signals: 75
* Directional win rate: 53.33%
* Net win rate after 2 bps friction: 44.00%
* Average net win: +16.6883 bps
* Average net loss: -9.8323 bps
* Net expectancy: +1.8367 bps/trade
* Approximate break-even win rate from average win/loss: 37.07%
* Approximate profit factor from average win/loss and realized net win rate: 1.33
* Average MFE across all trades: 19.6544 bps
* Average MAE across all trades: 13.9734 bps
* Average MFE when fixed-exit direction is correct: 24.8612 bps
* Average realized gross return when direction is correct: 15.5809 bps
* Average fixed-exit capture of winner MFE: 52.70%
* Winner MAE: 8.786 bps
* Loser MFE: 13.704 bps
* Loser MAE: 19.901 bps
* Hit +10 bps favorable excursion: 64.00%
* Hit +15 bps: 50.67%
* Hit +20 bps: 40.00%
* Hit +25 bps: 34.67%
* Hit +30 bps: 22.67%
* Hit +35 bps: 14.67%

Development interpretation: signal remains worth studying. Its average winner/loss geometry is cleaner than H1 and the fixed 10-minute exit appears inefficient.

## H3 gap reversion

* Signals: 42
* Directional win rate: 38.10%
* Net win rate after 2 bps friction: 38.10%
* Average net win: +49.5618 bps
* Average net loss: -56.9785 bps
* Net expectancy: -16.3917 bps/trade
* Approximate break-even win rate from average win/loss: 53.48%
* Approximate profit factor: 0.54
* Average MFE across all trades: 43.9516 bps
* Average MAE across all trades: 60.9465 bps
* Average MFE when fixed-exit direction is correct: 83.2191 bps
* Average realized gross return when direction is correct: 51.5618 bps
* Average fixed-exit capture of winner MFE: 54.21%
* Hit +10 bps favorable excursion: 78.57%
* Hit +20 bps: 64.29%
* Hit +30 bps: 50.00%

Development interpretation: large intraday movement exists, but the frozen direction is not economically useful. Large MFE by itself is not evidence of an edge because adverse excursion is larger and expectancy is negative.

## Revised research workflow

July remains the development set.

For signals that show useful development diagnostics:

1. Study win rate, payoff ratio, expectancy, MFE, MAE, target-hit curves, and exit capture.
2. Design a realistic stop, target, and/or time exit from the development data.
3. Freeze the complete candidate before inspecting August.
4. Run August exactly once as locked validation.
5. Judge primarily on net expectancy, win/loss structure, drawdown, and whether the observed behavior remains recognizable.
6. Use ticker and subperiod breakdowns as robustness diagnostics rather than automatic all-or-nothing rejection gates unless there is obvious single-source dependence.
7. Only after a historical survivor consider independent replication and prospective shadow.

Current development status:

* H1 ORB15: CONTINUE DEVELOPMENT
* H2 VWAP-volatility reversion: CONTINUE DEVELOPMENT
* H3 gap reversion: STOP DEVELOPMENT UNDER CURRENT DIRECTION
