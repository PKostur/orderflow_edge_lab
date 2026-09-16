# Discovery v2 Sprint 12 - Causal Setup-Level Meta Selection

Status: **CLOSED - NO FROZEN D0 RULE PASSED ALL HARD GATES**

Protocol freeze commit: `3bcbcdf92c1de02111a19a22a0bf89c8f54a4661`  
Pre-result clarification commit: `3ebc6e20148257089e324b78819a64c33e833fb4`  
Successful workflow run: `35134043644`  
Execution commit: `0265b21ee168a79447a357300212d79aba8afc3f`  
Immutable artifact: `discovery-v2-sprint12-meta-selection-v1`  
Artifact SHA-256: `72a1efbbbd2c957e61399a96a3e35145bb298a0a5342c4866203127f1d372926`

The first workflow attempt failed before market evaluation because scikit-learn was absent from the research dependencies. No market result was produced in that attempt. The dependency was added and the same frozen protocol was rerun.

## Frozen method

Each unchanged primary setup generator proposed a one-day next-open portfolio. A fixed eight-feature meta layer used only pre-entry information. For every eligible setup, a `StandardScaler -> L2 LogisticRegression(C=1)` model was refit on the latest 80 strictly prior labeled primary setups, with at least 60 required. A historical setup whose exit equaled the current entry timestamp was deliberately excluded from the current fit. The meta layer traded only when predicted probability of a positive standalone, fully round-tripped setup outcome was at least 0.60; otherwise it stayed in cash.

D0 bootstrap and LOSO were diagnostics, not hard gates. The selector still had to outperform its unchanged parent and its reversed-primary control, survive 1.5x transaction costs, and satisfy the frozen D0 concentration limits.

## meta_trend_acceleration_5d

State: `FALSIFIED` - **near-survivor; failed only the frozen top-5 positive-PnL concentration gate.**

- Scored setups: 66
- Accepted setups: 21
- Acceptance fraction: **31.82%**
- Accepted active-period net expectancy including transition-to-cash cost: **+32.00 bps**
- Ungated-parent active-period expectancy: **+28.70 bps**
- Advantage vs ungated parent: **+3.30 bps**
- Reversed-primary same-decisions expectancy: **-55.34 bps**
- Advantage vs reversed primary: **+87.34 bps**
- Accepted standalone-label mean: **+23.67 bps**
- Rejected standalone-label mean: **+12.50 bps**
- Accepted minus rejected: **+11.18 bps**
- Calendar-day mean net: **+5.65 bps/day**
- 1.5x-cost calendar mean: **+4.62 bps/day**
- Bootstrap 95% lower bound, diagnostic: **-4.44 bps/day**
- Minimum LOSO mean, diagnostic: **+0.92 bps/day**
- Best-symbol positive-PnL share: **37.60%** - pass
- Best-month positive-PnL share: **54.91%** - pass
- Top-5 positive-period share: **70.69%** - fail versus frozen 60% cap
- Walk-forward AUC, diagnostic: **0.450**

The five largest positive calendar periods were approximately +313.26, +241.23, +184.43, +165.38 and +145.27 bps. Their combined share of positive PnL caused the terminal D0 failure. No threshold or concentration rule is changed after observing this.

## meta_low_skew_90d

State: `FALSIFIED`

- Scored setups: 101
- Accepted setups: 15 - fails minimum 20
- Acceptance fraction: 14.85%
- Accepted active-period expectancy: **+1.93 bps**
- Ungated-parent active-period expectancy: **+5.91 bps**
- Advantage vs ungated parent: **-3.98 bps**
- Accepted standalone-label mean: **-11.40 bps**
- Rejected standalone-label mean: **-13.10 bps**
- 1.5x-cost calendar mean: **-0.21 bps/day**
- Walk-forward AUC: **0.520**

The meta layer did not add economic value.

## meta_funding_carry_14d

State: `FALSIFIED`

- Scored setups: 161
- Accepted setups: 24
- Acceptance fraction: 14.91%
- Accepted active-period expectancy: **+11.94 bps**
- Ungated-parent active-period expectancy: **+24.57 bps**
- Advantage vs ungated parent: **-12.63 bps**
- Accepted standalone-label mean: **+3.61 bps**
- Rejected standalone-label mean: **+7.15 bps**
- 1.5x-cost calendar mean: **+0.91 bps/day**
- Best-month positive-PnL share: **81.85%**
- Top-5 positive-period share: **69.13%**
- Walk-forward AUC: **0.518**

The selector preserved directionality but selected worse setups than the parent.

## Interpretation

Sprint 12 falsifies the exact frozen logistic meta-selection rules for all three families. It does not rescue any prior candidate ID and does not establish an edge.

The trend-acceleration result is materially different from the Sprint 11 dispersion gate: the setup-level meta layer improved accepted-trade expectancy versus the unchanged parent and separated accepted from rejected standalone outcomes. However, the realized result remained too concentrated under the frozen D0 rule and therefore cannot be promoted.

A future hypothesis may use the lesson that binary win/loss classification is not necessarily aligned with payoff magnitude. If tested, expected-return or payoff-aware selection must receive a new ID and be frozen before results. It may not retroactively alter Sprint 12.

Persistent edge established: **NO**  
Live execution supported: **NO**  
Leverage supported: **NO**
