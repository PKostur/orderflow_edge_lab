# Discovery v2 Sprint 1 — Findings

Run: GitHub Actions `35095715401`  
Artifact: `discovery-v2-sprint1-v1` / ID `10446505546`  
Artifact SHA-256: `324981ac31ced927f3836ee8053a2a01fe719113b5e89405340ddd5f7056ac02`  
Protocol freeze commit: `e228b3ffed6861db8aad2c5808806d1ad2fb73b9`  
Implementation contract commit: `e4c7617f51c45a53a4009d5926783ae62d2b7880`

## Result boundary

This was same-source historical **D0** falsification only. All three preregistered candidate directions are closed as `FALSIFIED`. No Sprint 1 result establishes a persistent trading edge or authorizes live execution.

## Preregistered candidate families

### 1. Dispersion-conditioned cross-sectional momentum — FALSIFIED

All four preregistered variants were negative after baseline costs.

| Variant | Observations | Mean gross bps | Mean cost bps | Mean net bps | 1.5x cost net bps |
|---|---:|---:|---:|---:|---:|
| disp60 | 26 | -64.735 | 7.692 | -72.427 | -76.274 |
| disp90 | 22 | -88.622 | 7.273 | -95.895 | -99.531 |
| disp120 | 18 | -47.710 | 6.389 | -54.099 | -57.293 |
| disp180 | 9 | -45.927 | 6.111 | -52.039 | -55.094 |

The ungated 30d/7d dollar-neutral momentum benchmark was also negative: about `-109.95 bps` per 7-day observation net.

The reversed-direction controls were positive, but they are **post-hoc hypothesis-generation evidence**, not a rescue of this failed family. Their sample was small and concentration remained problematic: e.g. `reverse_disp120` had only 18 observations, bootstrap lower bound below zero, best-month positive-PnL share about 72.7%, top-five positive-period share 100%, and negative minimum leave-one-symbol-out expectancy.

### 2. Extreme-funding reversal/carry — FALSIFIED

All four variants were negative gross and more negative after costs.

| Variant | Observations | Mean gross bps | Mean cost bps | Mean net bps | 95% block-bootstrap mean CI bps |
|---|---:|---:|---:|---:|---:|
| fund20 | 1484 | -5.138 | 5.539 | -10.677 | [-15.565, -5.943] |
| fund30 | 1464 | -2.570 | 4.959 | -7.529 | [-12.595, -2.332] |
| fund45 | 1434 | -2.937 | 4.324 | -7.261 | [-12.253, -2.028] |
| fund60 | 1404 | -3.394 | 3.946 | -7.340 | [-12.029, -2.806] |

The reversed-direction controls had slightly positive gross means, but transaction friction erased them; all remained negative net. No funding-family follow-up is justified from this run.

### 3. BTC-residual shock reversal — FALSIFIED

All four variants were strongly negative even before costs.

| Variant | Observations | Mean gross bps | Mean cost bps | Mean net bps | 95% block-bootstrap mean CI bps |
|---|---:|---:|---:|---:|---:|
| beta20 | 231 | -27.635 | 13.766 | -41.401 | [-58.926, -25.154] |
| beta30 | 221 | -27.623 | 14.072 | -41.696 | [-59.015, -24.711] |
| beta45 | 206 | -34.103 | 14.005 | -48.108 | [-65.681, -32.131] |
| beta60 | 191 | -36.440 | 13.927 | -50.366 | [-70.520, -32.517] |

The exact reversed controls — BTC-residual **momentum** — were positive across all four lookbacks:

| Control | Observations | Mean net bps | 1.5x cost net bps | 2.0x cost net bps | 95% bootstrap lower bps | Min leave-one-symbol-out mean bps |
|---|---:|---:|---:|---:|---:|---:|
| reverse_beta20 | 231 | 13.868 | 6.985 | 0.102 | -3.179 | 6.785 |
| reverse_beta30 | 221 | 13.551 | 6.515 | -0.522 | -4.018 | 5.522 |
| reverse_beta45 | 206 | 20.098 | 13.096 | 6.093 | 3.381 | 10.900 |
| reverse_beta60 | 191 | 22.513 | 15.549 | 8.586 | 4.016 | 13.901 |

For `reverse_beta45`, best-symbol positive-PnL share was ~33.6%, best-month share ~40.0%, top-five positive-period share ~19.8%; all are below the Discovery v2 50% concentration ceiling. `reverse_beta60` was similarly distributed.

## Interpretation

- The original residual-reversal hypothesis is decisively wrong on this D0 MEXC sample.
- The reversed residual-momentum behavior is broad enough to justify a **new candidate ID and new freeze**, using the preregistered stable-neighborhood rule rather than selecting the highest-PnL lookback.
- All four reversed lookbacks were positive at 1.5x friction. Following the precommitted upper-median rule for the ordered `[20, 30, 45, 60]` neighborhood selects **45 days**, not the historical maximum at 60 days.
- The 45-day residual-momentum rule must treat all Sprint 1 results as hypothesis-generation/development evidence. It requires a new freeze before any independent-source, independent-engine, later-period, or prospective evidence is examined.

## Closed IDs

The following Sprint 1 directions remain closed and may not be retuned under the same IDs:

- `dv2_s1_dispersion_xs_mom`
- `dv2_s1_funding_extreme_reversal`
- `dv2_s1_btc_residual_shock_reversal`
