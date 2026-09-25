# Payoff Geometry v1 — first completed diagnostic

## Provenance

- Analysis: `payoff_geometry_v1`
- Successful workflow run: `36146460935`
- Artifact ID: `10870356016`
- Artifact SHA-256: `f5be7e3aa0fda6ba9d630e5bbe1fc67cc9d91d8d9700bfb2d6d3738e6025b4be`
- Fixed cells per strategy: 71
- Frozen cell-set SHA-256: `04427db7d4b093c37be400c0746ee28377be6af98291a8ebca93c72db875bf62`
- Primary interpretation cost: 20 bps round trip
- Historical window: 2024-01-01 through exclusive 2026-09-12
- Terminal snapshot liquidations are excluded from the primary payoff-geometry cells.

This is same-period historical development evidence only.

## Main payoff-shape result

The diagnostic strongly confirms that hit rate alone is an incomplete description of these strategies.

| Strategy | Completed trades | Correct-direction rate | Median MFE, correct | Median MFE, incorrect | Correct/incorrect MFE ratio | Median MAE, correct | Median MAE, incorrect |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| DON8 | 220 | 36.8% | 4,089 bps | 777 bps | 5.26x | 442 bps | 1,316 bps |
| EMA8 | 332 | 25.6% | 4,181 bps | 570 bps | 7.34x | 238 bps | 881 bps |
| VOL8 | 2,095 | 37.8% | 592 bps | 135 bps | 4.37x | 92 bps | 278 bps |

Correct-direction trades also take much longer to reach their MFE:

- DON8: median 832h correct versus 80h incorrect;
- EMA8: 616h versus 56h;
- VOL8: 24h versus 0h.

This is consistent with positively skewed payoff geometry: relatively infrequent correct-direction episodes can travel much further than the more frequent incorrect episodes.

It is not, by itself, proof of a deployable edge.

## Causal pre-entry volatility state

The volatility labels use only completed pre-entry information:

- 20-bar close-to-close realized volatility;
- classified against the preceding 90-bar realized-volatility history;
- LOW / MID / HIGH causal terciles.

At 20 bps:

| Strategy | LOW n | HIGH n | LOW median MFE | HIGH median MFE | HIGH/LOW MFE | LOW median MAE | HIGH median MAE | LOW win rate | HIGH win rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| DON8 | 90 | 61 | 1,761 bps | 2,340 bps | 1.33x | 887 bps | 1,018 bps | 36.7% | 42.6% |
| EMA8 | 141 | 91 | 703 bps | 1,256 bps | 1.79x | 633 bps | 791 bps | 22.0% | 38.5% |
| VOL8 | 873 | 569 | 212 bps | 263 bps | 1.24x | 166 bps | 228 bps | 34.6% | 34.6% |

The VOL8 row is particularly useful for the research question: hit rate is effectively unchanged while the payoff excursion distribution moves.

However, HIGH volatility also raises adverse excursion, especially for VOL8. It is therefore not a simple volatility filter.

The 30-day shared-block bootstrap expectancy intervals still overlap zero for LOW and HIGH states in all three strategies. Examples:

- DON8 HIGH: about -527 to +2,970 bps;
- EMA8 HIGH: about -475 to +2,486 bps;
- VOL8 HIGH: about -83 to +405 bps.

No volatility filter is authorized.

## Session geometry

The fixed exclusive-session cells were all retained, including empty cells.

A notable same-period descriptive cell is DON8 `ASIA+LONDON`:

- 56 trades;
- expectancy about +1,825 bps;
- median MFE about 2,584 bps;
- block-bootstrap expectancy interval about +366 to +3,550 bps.

This is not a session promotion result. There are many predeclared cells and no decision-affecting multiplicity correction is being applied at this exploratory stage.

EMA8 and VOL8 show additional session differences, but their relevant expectancy intervals generally overlap zero.

## Alignment geometry

The payoff view is consistent with the earlier alignment diagnostics, while also showing their uncertainty.

DON8 BTC prior-bar:

- ALIGNED: 194 trades, expectancy about +602 bps, median MFE about 2,045 bps;
- AGAINST: 26 trades, expectancy about -554 bps, median MFE about 818 bps.

EMA8 own prior-three-bar:

- ALIGNED: 265 trades, expectancy about +339 bps, median MFE about 985 bps;
- AGAINST: 67 trades, expectancy about -83 bps, median MFE about 669 bps.

VOL8 own prior-three-bar:

- ALIGNED: 1,589 trades, expectancy about +49 bps, median MFE about 258 bps;
- AGAINST: 505 trades, expectancy about -10 bps, median MFE about 199 bps.

The shared-block bootstrap intervals remain wide enough that these are descriptive hypotheses, not authorized filters.

## Multiple-testing boundary

This diagnostic reports every predeclared cell and does not select a winner.

If a future result is used to change filtering, selection, promotion or deployment, it requires a new frozen decision protocol. The reserved methods for that later stage are:

- White's Reality Check;
- Hansen SPA;
- Deflated Sharpe Ratio;
- Probability of Backtest Overfitting.

They are not being used here to rescue or promote any historical cell.

## Prospective follow-up

The historical diagnostic generated one deliberately narrow structural follow-up:

**Does HIGH causal pre-entry volatility produce larger median MFE than LOW volatility on genuinely later completed trades?**

That question has been frozen separately in:

`config/payoff_geometry_forward_v1.json`

with prospective start:

`2026-09-25T16:00:00Z`

for DON8, EMA8 and VOL8 independently.

The forward watch does not filter the original trades and cannot authorize live trading or leverage.
