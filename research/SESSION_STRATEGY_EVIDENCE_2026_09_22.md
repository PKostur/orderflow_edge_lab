# MEXC order-flow session evidence baseline

Date: 2026-09-22

Source: successful Continuous Order-Flow Discovery run 35724999358, cumulative ledger/report artifacts.

This report is exploratory. It does not authorize a session filter, leverage, or live trading.

## Evidence set

* ENA_USDT with BTC_USDT context.
* 84 independent capture batches in the cumulative discovery ledger.
* 154,130 enriched fixed-horizon outcome rows across families, horizons and fee assumptions.
* Observation timestamps span 2026-09-12 through 2026-09-22 UTC.
* Session labels are reconstructed causally from each original `signal_observed_at_ns` using the frozen DST-aware trading-session protocol.
* Primary strategy comparison below uses 4 bps round-trip friction.

## Main result

Session context changes the relative behavior of several signal families, but session alone does not create a tradable after-cost edge.

At the 30-second horizon:

| Family | Session | Obs | Batches | Gross EV | Net EV @4bps | Cumulative net | Positive-batch fraction |
|---|---|---:|---:|---:|---:|---:|---:|
| aligned | Asia | 159 | 17 | -1.158 | -5.158 | -820.1 | 29.4% |
| aligned | London | 67 | 9 | -0.257 | -4.257 | -285.2 | 0.0% |
| aligned | London+NY | 195 | 13 | -0.591 | -4.591 | -895.3 | 30.8% |
| aligned | New York | 314 | 19 | -1.033 | -5.033 | -1,580.4 | 10.5% |
| cvd | London+NY | 1,176 | 13 | -0.345 | -4.345 | -5,109.9 | 7.7% |
| microprice | London+NY | 2,061 | 13 | -0.165 | -4.165 | -8,584.5 | 0.0% |

The London-New York overlap is relatively better for several families, especially compared with their all-session baselines, but the improvement is not large enough to overcome 4 bps friction.

## Horizon effect for aligned during London-New York overlap

| Horizon | Obs | Batches | Gross EV | Net EV @4bps |
|---|---:|---:|---:|---:|
| 5 s | 201 | 13 | +0.042 | -3.958 |
| 15 s | 200 | 13 | +0.026 | -3.974 |
| 30 s | 195 | 13 | -0.591 | -4.591 |

The overlap appears to improve the raw signal relative to the all-session aligned baseline, but it remains too small before costs.

## Exploratory interaction

A narrower state appeared inside the 30-second aligned London-New York sample:

* BTC flow alignment: `against`
* signal-strength bucket: `medium1.5-2.5`

Full fixed-horizon sample:

* 37 observations
* 10 batches
* gross EV: +5.161 bps/trade
* net EV at 4 bps: +1.161 bps/trade
* cumulative net at 4 bps: +42.953 bps
* net win rate: 40.5%
* average net winner: +26.23 bps
* average net loser: -15.93 bps
* net profit factor: 1.123
* median net trade: -2.60 bps
* max constant-notional drawdown: -192.38 bps
* positive-batch fraction: 50%
* largest positive trade share: 37.7%
* top-three positive trade share: 63.4%

At 8 bps friction the same state becomes:

* cumulative net: -105.05 bps
* EV: -2.839 bps/trade
* profit factor: 0.765
* positive-batch fraction: 20%

This is not robust enough to freeze as a candidate.

## Does this state actually travel farther?

The cumulative ledger contains frozen stop-risk MFE/MAE reports. For a consistent excursion proxy, the analysis uses:

* original stream
* RR target 3
* requested risk fraction 0.25%
* 4 bps friction
* 30-second fixed-horizon condition row

The stop-risk path can terminate at stop, target or time exit, so these MFE/MAE values are a risk-path proxy rather than unconstrained full-30-second extrema.

### Risk-eligible aligned observations

| Metric | London+NY aligned | London+NY + BTC-against + medium strength |
|---|---:|---:|
| Observations | 134 | 24 |
| Mean MFE | 9.59 bps | 12.16 bps |
| Median MFE | 4.86 bps | 3.72 bps |
| MFE p75 | 12.91 bps | 8.01 bps |
| MFE p90 | 24.42 bps | 18.12 bps |
| MFE p95 | 30.02 bps | 36.75 bps |
| Mean MAE | 9.36 bps | 7.48 bps |
| Median MAE | 5.68 bps | 5.49 bps |
| MFE >=10 bps | 31.3% | 20.8% |
| MFE >=20 bps | 15.7% | 12.5% |
| MFE >=30 bps | 5.2% | 8.3% |

The state has a higher mean MFE but a lower median, lower p75, lower p90 and lower 10/20-bps hit rates. One approximately 153.94 bps favorable excursion materially lifts the mean.

Therefore the current evidence does **not** support the broad claim that this state consistently travels farther. It supports a weaker interpretation: the state may have a fatter favorable right tail and somewhat lower average adverse excursion.

## Interpretation

### 1. Session is useful as a state variable

The economics do change by session. London-New York is repeatedly less poor for some families and horizons than their all-session behavior.

### 2. Session alone is insufficient

No broad session-conditioned family clears realistic 4 bps costs.

### 3. The first positive interaction is fragile

The 37-observation aligned/London-NY/BTC-against/medium-strength cell is positive at 4 bps but fails 8 bps stress, has only 50% positive batches and suffers a large drawdown.

### 4. Mean excursion is misleading here

The higher mean MFE in the narrow state is tail-driven. Median and intermediate quantiles do not improve. Future distance analysis must always report median and quantiles in addition to mean MFE.

### 5. BTC "against" deserves interpretation, not immediate filtering

Within London-New York, BTC flow being against the ENA signal performed better than BTC flow being aligned in this inspected sample. That could indicate short-horizon ENA reversion/decoupling behavior, a transient market regime, or sampling noise. It should be treated as a new explanatory hypothesis, not inverted into a production rule.

## Next evidence requirement

Keep the session definitions fixed and continue accumulating independent MEXC batches.

The automated cumulative reports now need to track whether the narrow state:

1. remains positive after 4 bps in later batches;
2. improves its positive-batch fraction above the current 50%;
3. avoids dependence on isolated large winners;
4. maintains a favorable MFE/MAE distribution in median and quantiles, not just mean;
5. remains interpretable under 8 bps stress even if it does not remain profitable there.

No candidate freeze is justified yet.


## Second interaction: CVD + wide spread + high range during London-New York

A systematic scan of one- and two-factor session interactions found 26 cells with positive 4-bps EV under the exploratory minimum of 30 observations and 8 batches. This multiple-comparison count is itself a warning against selecting the highest endpoint result.

The most notable movement-state cell was:

* family: `cvd`
* session: `LONDON+NEW_YORK`
* spread bucket: `wide>3`
* range-to-spread bucket: `high>6`
* 30 unique fixed-horizon observations across 9 batches

### Fixed-horizon economics

| Horizon | Gross EV | Net EV @4bps | Cum net @4bps | Net EV @8bps | Cum net @8bps |
|---|---:|---:|---:|---:|---:|
| 5 s | +6.082 | +2.082 | +62.45 | -1.918 | -57.55 |
| 15 s | +9.366 | +5.366 | +160.97 | +1.366 | +40.97 |
| 30 s | +11.244 | +7.244 | +217.32 | +3.244 | +97.32 |

At 30 seconds and 4 bps:

* win rate: 50.0%
* average winner: +38.59 bps
* average loser: -24.11 bps
* profit factor: 1.60
* max constant-notional drawdown: -150.85 bps
* positive-batch fraction: only 33.3% (3/9)
* top-three positive-trade share: 58.5%
* average observed spread: 4.37 bps
* median observed spread: 4.05 bps
* maximum observed spread: 8.54 bps

At 8 bps the 30-second endpoint remains arithmetically positive, but positive-batch fraction falls to 22.2% (2/9).

### Excursion behavior

The frozen stop-risk path contains 11 risk-eligible observations from this state.

| Metric | General CVD London+NY | Wide-spread/high-range state |
|---|---:|---:|
| Risk-eligible observations | 390 | 11 |
| Mean MFE | 7.71 bps | 37.32 bps |
| Median MFE | 3.31 bps | 16.44 bps |
| MFE p75 | 10.95 bps | 48.09 bps |
| MFE p90 | 21.31 bps | 85.81 bps |
| MFE >=10 bps | 27.7% | 63.6% |
| MFE >=20 bps | 11.0% | 45.5% |
| MFE >=30 bps | 4.4% | 36.4% |
| Mean MAE | 7.41 bps | 13.85 bps |
| Median MAE | 5.62 bps | 11.90 bps |

Unlike the earlier aligned/BTC-against clue, the MFE shift here is visible in the median and intermediate quantiles, not only in the mean. This is stronger evidence that the state identifies **greater post-entry movement**.

However, adverse excursion also rises substantially. The state therefore looks primarily like a high-movement/high-risk regime. The current evidence does not yet establish that CVD direction reliably predicts that movement.

The practical research question becomes:

> When London and New York overlap and ENA enters a wide-spread/high-range state, what additional directional variable separates the large favorable excursions from the equally elevated adverse excursions?

That is a better next conditioning problem than simply filtering for the session itself.


## Directional separator inside the CVD high-movement state

Within the 30 CVD / London-New-York / wide-spread / high-range observations, winners and losers were split 15/15 at 4 bps.

The strongest categorical separator was BTC flow relation:

* Winners: 10 BTC-against, 4 BTC-aligned, 1 neutral.
* Losers: 4 BTC-against, 11 BTC-aligned.

Other causal variables showed smaller differences:

* median signal-strength multiple: winners 3.65, losers 2.81;
* median quote-update rate: winners 286.6/s, losers 153.3/s;
* median rolling 10-second trade count: winners 17, losers 15;
* local 15-second return was aligned with the ENA signal in 13/15 winners **and** 13/15 losers, so local price-direction agreement did not separate outcomes in this sample.

### BTC-against subset

The same 14 BTC-against signals are observable at each fixed horizon:

| Horizon | Obs | Batches | Gross EV | Net EV @4bps | Net EV @8bps | Cum net @4bps | 4bps WR |
|---|---:|---:|---:|---:|---:|---:|---:|
| 5 s | 14 | 4 | +8.57 | +4.57 | +0.57 | +63.9 | 64.3% |
| 15 s | 14 | 4 | +18.11 | +14.11 | +10.11 | +197.5 | 57.1% |
| 30 s | 14 | 4 | +33.06 | +29.06 | +25.06 | +406.8 | 71.4% |

For comparison, the 15 BTC-aligned observations at 30 seconds had:

* gross EV: -11.11 bps;
* net EV at 4 bps: -15.11 bps;
* win rate: 26.7%;
* cumulative net: -226.6 bps.

This is a large separation, but the BTC-against result spans only four independent capture batches. It is therefore a **watch hypothesis**, not evidence sufficient for a candidate freeze.

### Excursion proxy split by BTC relation

Among risk-eligible observations from the same high-movement state:

| BTC relation | Obs | Mean MFE | Median MFE | Mean MAE | Median MAE | Fixed-horizon gross EV |
|---|---:|---:|---:|---:|---:|---:|
| Against | 5 | 48.54 | 26.73 | 12.49 | 8.54 | +35.47 |
| Aligned | 6 | 27.97 | 14.84 | 14.97 | 15.18 | -3.45 |

The sample is very small, but the direction of the excursion evidence is consistent with the fixed-horizon result: BTC-against observations show more favorable travel and somewhat less adverse travel.

## Working hypothesis

The current hypothesis is not simply "trade London-New-York."

It is:

> During the London-New-York overlap, when ENA is already in a wide-spread/high-range state, CVD signals may have more directional value when short-horizon BTC flow is opposite the ENA signal rather than aligned with it.

A plausible market interpretation is temporary ENA-specific flow/decoupling during a high-liquidity, high-volatility period. That interpretation is unproven.

The next independent batches should test this exact state without changing its definition. The key evidence is cumulative after-cost return, positive-batch fraction, median MFE/MAE and whether the BTC-against versus BTC-aligned separation persists.


## Incremental update: two later New-York-only captures

After the original 84-batch discovery artifact, two additional successful main-branch Continuous Order-Flow Discovery runs completed at approximately 16:06 UTC and 16:55 UTC.

These captures occurred after the London session had ended, so they add New-York-only evidence and contain no W3 London-New-York observations.

At the 30-second horizon and 4 bps friction, the incremental observations were:

| Family | New obs | New batches | Incremental EV | Incremental cumulative net | Incremental WR |
|---|---:|---:|---:|---:|---:|
| aligned | 10 | 2 | -5.90 bps | -58.99 bps | 30.0% |
| aligned_btc | 5 | 2 | -7.41 | -37.05 | 20.0% |
| book | 133 | 2 | -4.03 | -535.44 | 39.1% |
| cvd | 107 | 2 | -5.56 | -594.91 | 32.7% |
| microprice | 256 | 2 | -3.55 | -908.04 | 39.5% |

The updated full New-York-only 30-second / 4-bps results remain negative for every family:

| Family | Obs | Batches | EV | Cumulative net | Positive batches |
|---|---:|---:|---:|---:|---:|
| aligned | 324 | 21 | -5.06 bps | -1,639.39 bps | 14.3% |
| aligned_btc | 159 | 20 | -6.99 | -1,110.89 | 15.0% |
| book | 1,972 | 22 | -5.49 | -10,830.41 | 0.0% |
| cvd | 1,744 | 22 | -4.64 | -8,094.87 | 13.6% |
| microprice | 3,311 | 22 | -4.65 | -15,392.17 | 0.0% |

This strengthens the earlier conclusion that New York's higher movement does not by itself create directional expectancy for the existing signal families.

### Prospective-watch status at this update

* W1 aligned-short Asia-opening: no new eligible Asia-opening evidence in these two NY captures.
* W2 aligned-BTC-short Asia-opening: no new eligible Asia-opening evidence in these two NY captures.
* W3 CVD London-NY / wide-spread / high-range / BTC-against: no eligible observations because both new captures began after the London session closed.

No watch has reached a prospective review target.
