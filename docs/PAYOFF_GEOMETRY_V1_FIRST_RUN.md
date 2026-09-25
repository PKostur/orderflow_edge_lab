# Payoff Geometry v1 — first frozen historical run

## Evidence identity

- Workflow run: `36146460935`
- Artifact: `payoff-geometry-v1`
- Artifact id: `10870356016`
- Artifact digest: `sha256:f5be7e3aa0fda6ba9d630e5bbe1fc67cc9d91d8d9700bfb2d6d3738e6025b4be`
- Fixed cell-set SHA256: `04427db7d4b093c37be400c0746ee28377be6af98291a8ebca93c72db875bf62`
- Historical source window: frozen universal-existing 8h development snapshot
- Primary economics shown below: 20 bps round-trip cost
- Bootstrap: 500 shared 30-day calendar-block resamples

This is same-period historical development evidence only. It does not authorize a session, volatility, alignment, side, or outcome filter.

## Overall geometry

| Strategy | Trades | Win | Exp bps | Exp 95% block CI | Median MFE | Median abs MAE | Median gross/MFE | Median time to MFE |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| DON8 | 220 | 35.5% | 465.5 | [-230.8, 1174.4] | 1941.9 | 974.4 | -0.395 | 300h |
| EMA8 | 332 | 25.3% | 254.1 | [-214.5, 807.8] | 951.0 | 744.5 | -0.666 | 104h |
| VOL8 | 2095 | 34.5% | 34.9 | [-33.8, 135.5] | 234.5 | 188.5 | -0.299 | 8h |

The bootstrap expectancy intervals cross zero for all three overall cells. Point estimates therefore remain descriptive.

## Correct versus incorrect direction

Outcome is defined only by frozen episode gross return: `gross_bps > 0`.

| Strategy | Outcome | N | Median MFE | Median abs MAE | Median gross/MFE | Median time to MFE |
|---|---|---:|---:|---:|---:|---:|
| DON8 | Correct | 81 | 4089.1 | 441.8 | 0.396 | 832h |
| DON8 | Incorrect | 139 | 777.0 | 1315.9 | -1.525 | 80h |
| EMA8 | Correct | 85 | 4180.8 | 238.1 | 0.460 | 616h |
| EMA8 | Incorrect | 247 | 570.0 | 880.6 | -1.183 | 56h |
| VOL8 | Correct | 792 | 592.5 | 91.7 | 0.365 | 24h |
| VOL8 | Incorrect | 1303 | 135.5 | 277.9 | -1.136 | 0h |

The diagnostic confirms that the winning side of the payoff distribution is characterized by much larger favorable excursion and much lower adverse excursion. It also shows that median realized gross capture of winner MFE is only about 0.37–0.46.

This outcome split is descriptive geometry, not a causal entry filter: outcome is known only after the episode.

## Causal pre-entry volatility cells

Volatility state uses only completed information before entry: 20-bar realized close-to-close volatility ranked against the preceding 90-bar history.

| Strategy | Vol state | N | Win | Exp bps | Median MFE | Median abs MAE | Median winner gross/MFE |
|---|---|---:|---:|---:|---:|---:|---:|
| DON8 | LOW | 90 | 36.7% | 290.8 | 1760.9 | 887.1 | 0.318 |
| DON8 | MID | 69 | 27.5% | 167.0 | 1830.4 | 1041.5 | 0.438 |
| DON8 | HIGH | 61 | 42.6% | 1061.0 | 2339.7 | 1018.0 | 0.474 |
| EMA8 | LOW | 141 | 22.0% | 208.8 | 703.5 | 633.5 | 0.469 |
| EMA8 | MID | 100 | 18.0% | -53.0 | 824.4 | 836.1 | 0.525 |
| EMA8 | HIGH | 91 | 38.5% | 662.0 | 1256.0 | 791.2 | 0.413 |
| VOL8 | LOW | 873 | 34.6% | 18.2 | 212.2 | 165.6 | 0.376 |
| VOL8 | MID | 653 | 34.3% | 2.4 | 255.0 | 197.4 | 0.321 |
| VOL8 | HIGH | 569 | 34.6% | 97.9 | 263.0 | 227.6 | 0.403 |

The clearest payoff-geometry example is VOL8: hit rate is almost unchanged across the three causal volatility states while median favorable excursion rises with volatility. That is consistent with studying move magnitude separately from win rate.

This does not establish a tradable volatility filter. The corresponding block-bootstrap expectancy intervals all cross zero:

- VOL8 LOW: approximately [-45.2, 92.6] bps
- VOL8 MID: approximately [-53.5, 73.3] bps
- VOL8 HIGH: approximately [-82.5, 405.0] bps

DON8 and EMA8 also have higher median MFE in HIGH than LOW volatility, but their hit rates move materially as well and their cell expectancy intervals are wide.

## Fixed-cell completeness

Every preregistered cell is retained, including empty cells.

At 20 bps each strategy has 71 cells. Empty cells are expected because 8h entry timestamps cannot realize every theoretical session-overlap combination and some strategy/alignment states never occur.

The full artifact retains:

- ALL;
- OUTCOME;
- SIDE;
- PRE_ENTRY_VOLATILITY;
- all eight fixed SESSION regimes;
- BTC prior-bar states;
- own prior-three-bar states;
- all SESSION × BTC-prior-bar combinations;
- all SESSION × own-prior-three-bar combinations.

Interaction cells are deliberately not ranked here. The artifact is the canonical complete cell report.

## Inference boundary

The shared block bootstrap is used only to show uncertainty while preserving calendar dependence across overlapping strategy/symbol observations.

No cell is promoted from this diagnostic. If a later claim would change candidate selection, filtering, promotion, or deployment, it requires a new frozen decision protocol and the reserved multiple-testing controls:

- White Reality Check;
- Hansen SPA;
- Deflated Sharpe Ratio;
- Probability of Backtest Overfitting.

No result in this run establishes profitable edge, future OOS evidence, live authorization, or leverage authorization.
