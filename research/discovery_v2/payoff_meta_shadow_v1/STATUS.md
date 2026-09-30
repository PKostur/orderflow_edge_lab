# DV2 Payoff-Meta Trend-Acceleration Research Shadow v1

Status: **FROZEN - PRE-START**

Shadow ID: `dv2_payoff_meta_trend_accel_shadow_v1`  
Prospective boundary: `2026-09-17T00:00:00Z`  
Freeze commit: `626bf76572c76653789f1a6940a9a6ba395edaba`  
Workflow implementation commit: `544fac7d9411245dd0f97b064a6f3f2bbb356396`  
Initial workflow run: `35135300964`  
Initial artifact: `dv2-payoff-meta-forward-shadow-v1`  
Initial artifact SHA-256: `cc4101b1a43132e7d6e7930819819433b8fc24d679d27f77fae34911669eeae2`

## Source rule status

The source Sprint 13 rule remains `FALSIFIED`. This shadow is not a candidate promotion and is not D4 validation. It exists only to collect genuinely new observations for the exact frozen rule after the prospective boundary.

Exact frozen rule:

- Primary: 5-day cross-sectional trend acceleration, long top two / short bottom two, BTC Wilder ADX14 >=25.
- Meta features: exact eight causal features frozen for Sprint 12.
- Model: `StandardScaler -> Ridge(alpha=10)`.
- Training: latest 80 strictly prior labeled primary setups, minimum 60.
- Same-open previous setup exits are excluded from the current fit.
- Action: `TRADE` only if predicted standalone net bps >0; otherwise `PASS`.
- 1x gross maximum exposure, actual realized funding, 10 bps/side actual turnover.
- No retuning after the prospective start.

## Initial boundary check

The initial workflow ran before the prospective boundary and correctly produced:

- status: `PRE_START`
- completed forward setups: **0**
- accepted completed setups: **0**
- source fetch before start: **skipped**
- pre-start PnL included in forward metrics: **NO**

This establishes a clean zero-evidence starting point.

## Forward evidence accounting

After the boundary, each workflow snapshot will preserve:

1. an append-only-style completed setup ledger containing only entries at or after the prospective start, with each setup's frozen model prediction, TRADE/PASS decision and fully round-tripped standalone realized payoff once its exit is available;
2. accepted-versus-rejected prospective payoff diagnostics;
3. a sequential paper-portfolio snapshot for comparison with the original Sprint 13 accounting;
4. the latest open decision, if a new post-start primary setup exists but has not completed.

No new pass/fail gate is applied during this shadow. It is evidence collection, not another retrospective optimization cycle.

## Scheduling note

The workflow contains a daily `01:15 UTC` cron and manual dispatch. GitHub scheduled workflows execute from the repository default branch, so the cron is only active if this exact frozen workflow is deliberately placed on the default branch. The current research branch does not by itself make the schedule operational.

Persistent edge established: **NO**  
D0 passed: **NO**  
Candidate promoted: **NO**  
D4 validation: **NO**  
Live execution supported: **NO**  
Leverage supported: **NO**
