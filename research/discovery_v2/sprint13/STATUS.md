# Discovery v2 Sprint 13 - Payoff-Aware Meta Selection

Status: **CLOSED - FROZEN D0 RULE FALSIFIED BY ACCEPTANCE-FRACTION GATE**

Protocol freeze commit: `815df9b5c3acec3b66d7b145ac7a9fabdd0524a3`  
Workflow run: `35134566276`  
Execution commit: `fc296aafe0815efd0eac3b0add90eec6ff2ba46d`  
Immutable artifact: `discovery-v2-sprint13-payoff-meta-v1`  
Artifact SHA-256: `f214b938b118e2de7925e8f5c5c2105f7dd85ac42c0edfd8bc34aba3d17fc0ae`

## Frozen rule

The unchanged 5-day trend-acceleration primary proposed a one-day, 1x gross, market-neutral cross-sectional setup only while BTC Wilder ADX14 was at least 25. The meta layer used the exact eight causal features inherited from Sprint 12 and fit `StandardScaler -> Ridge(alpha=10)` on the latest 80 strictly prior standalone setup payoffs, with at least 60 prior setups required. A prior setup whose exit timestamp equaled the current entry timestamp was excluded from the current fit.

The meta action was frozen as:

- `TRADE` if predicted standalone net bps > 0
- otherwise `PASS` and remain in cash

There was one model, one zero-bps threshold and no model, feature or threshold grid.

## D0 result

State: `FALSIFIED`

The frozen rule passed every economic, direction, concentration and selector-value hard check except the maximum acceptance-fraction check.

- Scored setups: **66**
- Accepted setups: **40**
- Rejected setups: **26**
- Acceptance fraction: **60.6061%**
- Frozen maximum acceptance fraction: **60.0000%** - **FAIL**
- Positive accepted setups: **24**
- Accepted active-period net expectancy including transitions to cash: **+32.36 bps**
- Ungated-parent active-period expectancy: **+28.70 bps**
- Advantage vs ungated parent: **+3.66 bps**
- Reversed-primary same-decisions expectancy: **-53.36 bps**
- Advantage vs reversed primary: **+85.73 bps**
- Accepted standalone payoff mean: **+22.86 bps**
- Rejected standalone payoff mean: **+5.57 bps**
- Accepted minus rejected standalone payoff: **+17.29 bps**
- Calendar-day mean net: **+10.88 bps/day**
- Calendar-day mean at 1.5x transaction costs: **+9.11 bps/day**
- Minimum leave-one-symbol-out mean, diagnostic: **+0.11 bps/day**
- Bootstrap 95% lower bound, diagnostic: **-1.92 bps/day**
- Best-symbol positive-PnL share: **48.56%**
- Best-month positive-PnL share: **51.57%**
- Maximum single positive-period share: **11.90%**
- Top-5 positive-period share, diagnostic: **44.40%**
- Prediction/realized-payoff rank correlation, diagnostic: **+0.104**

The smallest positive prediction accepted by the frozen rule was still above zero. No threshold is raised after observing the result, and the 60% acceptance cap is not rounded or reinterpreted. Forty accepted setups out of 66 is 60.6061%, so the rule fails exactly as frozen.

## Interpretation

This is a near-survivor, not a candidate. Sprint 13 provides evidence that payoff-aware setup selection can improve the unchanged trend-acceleration parent on this contaminated 2026 development sample, but that evidence is not independent and does not satisfy the complete frozen D0 contract.

No Binance D2 or 2025 D3 validation is authorized for this ID. A separate prospective research shadow may preserve this exact rule unchanged to gather genuinely new post-freeze observations. Such a shadow is research-only and cannot retroactively convert Sprint 13 into a D0 pass.

Persistent edge established: **NO**  
Live execution supported: **NO**  
Leverage supported: **NO**
