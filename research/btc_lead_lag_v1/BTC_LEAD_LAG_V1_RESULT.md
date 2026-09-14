# BTC Lead Lag V1 Result

## Evidence boundary

This result is development-only historical evidence under the frozen `btc-lead-lag-v1-state-first` protocol and the pre-outcome reliability amendment `btc-lead-lag-v1.1-pre-outcome-reliability`.

The first implementation was declared inadmissible before outcome inspection because it did not fully enforce all predeclared controls. This report records only the corrected exact-head run.

## Canonical run

- Exact branch head: `a0af91e399b7b38d68836ea1ef37261eccb1381a`
- Workflow: `BTC Lead Lag V1`
- Workflow run: `34906421033`
- Artifact: `btc-lead-lag-v1`
- Artifact ID: `10371944491`
- Artifact SHA256: `4f575b308052814ae1026bea80a0b26b8b6cf2fd5670cc23692232da89cc8ff0`
- Symbols with data: 9
- Frozen state variants: 16

## Result

- State passes: **0 / 16**
- Economic rows opened: **0**
- Primary economic passes: **0**

Because no state variant passed the predeclared market-state gate, the strategy-PnL layer remained closed. No 12/16/20 bps execution economics, reversed-direction economics, time-shift economics, beta-hedged two-leg economics, stop optimization, MAE/MFE candidate work, holdout, paper promotion, or live execution was opened from this lane.

## Decision

Reject `btc-lead-lag-v1` at the state layer. Do not tune lag, lookback, beta window, horizon, thresholds, or controls against this inspected period to rescue the family.

Any future BTC lead-lag hypothesis must be separately versioned before new evidence and should represent a materially different mechanism or new dependence cluster rather than a local parameter rescue.

## Claims

- Profitable edge established: **false**
- Untouched OOS evidence: **false**
- Paper promotion authorized: **false**
- Live order transmission authorized: **false**
