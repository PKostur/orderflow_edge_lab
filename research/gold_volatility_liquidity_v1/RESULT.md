# Gold Volatility and Liquidity v1: development state result

## Evidence identity

- branch: `research/gold-volatility-liquidity-v1`
- canonical workflow run: `34986544522`
- canonical scored head: `02b30952bcc4fb9f0e2921a418f74250bc77d47c`
- artifact ID: `10403373273`
- artifact digest: `sha256:8cb87379f7ae2b637f7c10d88d9cfb1592a55bea11bb754d6ec5eee7248e28fe`
- source: pinned Dukascopy XAUUSD M1 bid/ask
- source commit: `922f83a60cc574e7395fb27397077288055a1ef6`
- input rows: `1,139,040`
- input start: `2020-11-01T00:00:00+00:00`
- input end: `2022-12-31T23:59:00+00:00`
- development observations: `5,446`
- New York development dates represented: `517`
- locked 2023 validation opened: **no**
- directional scoring run: **no**
- economic/PnL scoring run: **no**

## Result

One of five frozen volatility-state hypotheses passed every applicable gate:

`rv_persistence`

The surviving state is simple: relative to its own trailing same-clock history, unusually high realized volatility during the previous hour tends to be followed by unusually high realized volatility during the next hour.

This is a volatility-state result only. It does not establish price direction or profitability.

## Primary hypothesis table

| Hypothesis | Primary effect | Raw p | BH q | Daily sign fraction | Positive clock slots | 2021 / 2022 sign | Secondary range sign | State pass |
|---|---:|---:|---:|---:|---:|---|---|---|
| RV persistence | +0.2871 median daily Spearman | 0.000050 | 0.000125 | 77.04% | 11 / 11 scorable | positive / positive | positive | **yes** |
| Spread level incremental | -0.0086 partial Spearman | 0.6720 | 0.8015 | 50.19% | 2 / 11 | negative / positive | negative | no |
| Spread deterioration incremental | +0.0069 partial Spearman | 0.8015 | 0.8015 | 50.78% | 3 / 11 | positive / negative | positive | no |
| Range state incremental | +0.0865 partial Spearman | 0.000050 | 0.000125 | 60.51% | 9 / 11 | positive / positive | positive | no: frozen effect-size floor was 0.15 |
| Negative semivariance incremental | +0.0360 partial Spearman | 0.1412 | 0.2354 | 53.50% | 9 / 11 | positive / negative | positive | no |

## RV persistence breadth

Primary median daily Spearman:

`+0.287121`

Year decomposition:

- 2021: `+0.281818`
- 2022: `+0.290909`

Daily discovered-sign fraction:

`77.04%`

Secondary target, next-hour high-low range ratio:

`+0.140909` median daily effect, same positive sign.

Per-clock-slot Spearman against next-hour realized-volatility ratio:

- 00:00 New York: `+0.4960`
- 02:00: `+0.5316`
- 04:00: `+0.5472`
- 06:00: `+0.5642`
- 08:00: `+0.2944`
- 10:00: `+0.5145`
- 12:00: `+0.6411`
- 14:00: `+0.5854`
- 16:00: `+0.6116`
- 20:00: `+0.4987`
- 22:00: `+0.5649`

The 18:00 New York slot produced no scorable observations because exact required bars were unavailable. The frozen protocol prohibited interpolation, so that slot was absent rather than repaired after inspection.

All 11 actually scorable slots have the same positive sign.

## What did not survive

### Bid-ask spread level

After controlling for pre-existing realized-volatility state, spread level adds essentially no stable next-hour volatility information in this implementation.

### Recent spread deterioration

The last-15-minute versus prior-45-minute spread ratio also adds no stable incremental information.

### Range state

Range state is statistically clear but too small under the predeclared economic-relevance floor. Its primary partial effect is only `+0.0865`, below the frozen `0.15` minimum. The threshold is not weakened after observation.

### Negative semivariance share

The effect is small and changes sign between 2021 and 2022. It is rejected.

## Promotion decision

Promote only the continuous `rv_persistence` state to mechanism-generation status.

Do not promote spread, spread deterioration, range state, or negative-semivariance variants.

The next step must not directly claim a profitable trade. High future volatility has no inherent directional sign. The next research stage therefore needs a separately frozen directional/executable mechanism that can plausibly convert the state into returns without assuming a direction that this study never predicted.

The preferred next mechanism is a high-volatility breakout-continuation state study. It should define a deterministic breakout after an elevated pre-RV state, test post-breakout directional continuation before PnL, and keep 2023 sealed. Only if that directional state survives may an execution/cost model be frozen.

## Claims

- Gold next-hour volatility state information established in 2021-2022 development: **yes, for RV persistence only**
- price-direction edge established: **no**
- executable edge established: **no**
- profitable edge established: **no**
- verified future OOS: **no**
- leverage authorized: **no**
- live enabled: **no**
