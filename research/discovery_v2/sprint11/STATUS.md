# Discovery v2 Sprint 11 - Selective Opportunity Qualification

Status: **CLOSED - ALL THREE FROZEN SELECTIVE RULES FALSIFIED**

Protocol freeze commit: `c48623ce31bc1f5032635049f0a69f457e55af82`
Workflow run: `35132795661`
Immutable artifact: `discovery-v2-sprint11-selective-v1`
Artifact SHA-256: `e466ca6f9bcbc86bc3dee52f9975806dbc0e592b73746ff2fbe1a548e44a2f35`

## What Sprint 11 tested

Sprint 11 changed D0 discovery so a strategy could explicitly remain in cash. Each family had one frozen opportunity-quality rule: trade only when cross-sectional score spread exceeded its strictly-prior 60-day 75th percentile. Trend acceleration additionally required prior-state BTC ADX14 >= 25. There was no threshold grid and no post-result substitution.

A selective rule had to beat both its same-gate reversed control and its own ungated parent. Bootstrap and LOSO were diagnostic at D0 rather than hard gates, but would become hard again in D2/D3 for any surviving research candidate.

## Results

### selective_trend_acceleration_5d

State: `FALSIFIED`

- Active periods: 29 / 242 (11.98%)
- Active-period net expectancy including transition-to-cash cost: **-3.14 bps**
- Ungated-parent active-period expectancy: **+13.17 bps**
- Selective minus ungated parent: **-16.31 bps**
- Same-gate reversed active expectancy: **-16.86 bps**
- Selective minus reversed: **+13.71 bps**
- Calendar-day mean net: **-0.38 bps/day**
- 1.5x-cost calendar mean: **-0.98 bps/day**
- Bootstrap lower bound: **-6.99 bps/day**
- Minimum LOSO mean: **-2.76 bps/day**

The opportunity gate removed many trades but selected a worse subset than the ungated trend-acceleration parent.

### selective_low_skew_90d

State: `FALSIFIED`

- Active periods: 50 / 162 (30.86%)
- Active-period net expectancy including transition-to-cash cost: **+0.89 bps**
- Ungated-parent active-period expectancy: **+13.96 bps**
- Selective minus ungated parent: **-13.07 bps**
- Same-gate reversed active expectancy: **-7.29 bps**
- Selective minus reversed: **+8.18 bps**
- Calendar-day mean net: **+0.27 bps/day**
- 1.5x-cost calendar mean: **-0.22 bps/day**
- Bootstrap lower bound: **-5.62 bps/day**
- Minimum LOSO mean: **-4.28 bps/day**
- Best-symbol positive-PnL share: **66.75%**
- Best-month positive-PnL share: **74.00%**

The filter preserved the correct directional relationship versus the reversed strategy, but selected far worse opportunities than simply trading the parent signal whenever available.

### selective_funding_carry_14d

State: `FALSIFIED`

- Active periods: 28 / 238 (11.76%)
- Active-period net expectancy including transition-to-cash cost: **+0.13 bps**
- Ungated-parent active-period expectancy: **+15.36 bps**
- Selective minus ungated parent: **-15.23 bps**
- Same-gate reversed active expectancy: **-13.35 bps**
- Selective minus reversed: **+13.48 bps**
- Calendar-day mean net: **+0.02 bps/day**
- 1.5x-cost calendar mean: **-0.37 bps/day**
- Bootstrap lower bound: **-3.14 bps/day**
- Minimum LOSO mean: **-1.46 bps/day**
- Best-month positive-PnL share: **94.96%**

Again, high score dispersion was not a useful opportunity-quality proxy.

## Interpretation

This result falsifies the **specific Sprint 11 selector**, not the broader hypothesis that selective trading can improve expectancy. The failed common assumption was that unusually wide cross-sectional score dispersion identifies the best setups. In all three families, the selective subset had materially lower active-period expectancy than its own ungated parent.

A future selective hypothesis must receive a new ID and freeze. Do not retune the 75th percentile on this sample. A more faithful next test is setup-level qualification: a primary signal proposes trades, and a causal secondary decision layer decides whether each proposed setup should be taken based only on features known before entry. Any such layer must be walk-forward and compared directly with the unchanged primary strategy.

Persistent edge established: **NO**  
Live execution supported: **NO**  
Leverage supported: **NO**
