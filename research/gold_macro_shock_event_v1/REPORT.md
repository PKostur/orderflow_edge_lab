# Gold Macro-Shock Event v1 — Development Result

## Evidence boundary

This is a post-observation retrospective development study, not future OOS.

Protocol frozen before scoring at `64bd1f40e9e210d4f9f3b0d3098cc32be8d28f8b`.
Canonical workflow run: `34970415415`.
Canonical source head: `b4afe8177e6e8a6568c083a5c9df46446a8b7819`.
Artifact: `gold-macro-shock-event-v1` (`10397455851`).
Artifact digest: `sha256:de04425915cbc23d4bada9146cc4388e39d435142f377f5c287cb527b9b3d1b3`.

2021-2023 locked validation and 2024-2026 retrospective extension remained unopened. No leverage was tested.

## Frozen design

The experiment changed return source entirely from gold/silver convergence. It formed a causal daily macro-shock score from lagged and rolling-standardized one-day moves in:

- VIX: positive shock contribution when volatility rises;
- broad USD: positive gold shock contribution when the dollar falls;
- 10-year real yield: positive gold shock contribution when real yield falls.

Composite: `(z_VIX - z_USD - z_real_yield) / sqrt(3)`.

Predeclared grid:

- event thresholds: |composite| >= 1.5 / 2.0
- horizons: 5 / 10 trading days
- modes: continuation / reversal
- total unique hypotheses: 8
- 20,000 dependence-aware sign-flip epochs per hypothesis
- BH-FDR q <= 0.10 state gate
- next-open entry, fixed-horizon open exit
- one active trade
- 2.5 / 5 / 10 bps costs; primary 5 bps
- equal-timing long-gold benchmark
- both long and short subsets required to be positive

## Canonical outcome

- development rows: **2,846**
- complete macro-score rows: **2,753**
- hypotheses: **8**
- state passes: **0**
- economic passes: **0**
- candidates frozen: **0**

### State evidence

Continuation hypotheses have negative median state correlation:

- |shock|>=1.5, 5d: rho **-0.0412**, 27 folds, q **1.0**
- |shock|>=1.5, 10d: rho **-0.0575**, 26 folds, q **1.0**
- |shock|>=2.0, 5d: rho **-0.2184**, only 8 folds, q **1.0**
- |shock|>=2.0, 10d: rho **-0.0675**, only 8 folds, q **1.0**

The predeclared reversal hypotheses flip the sign but still fail significance/breadth. Best reversal point estimate is |shock|>=2.0 / 5d at rho **+0.2184**, but it has only 8 scorable folds and q **0.6242**.

## Economic diagnostics

No PnL cell can promote because no state hypothesis passes.

The strongest-looking diagnostic is:

`continuation__abs2p0__h10`

- trades: **79**
- median-fold net at 5 bps: **+31.29 bps**
- median-fold PF: **1.68**
- positive economic folds: **62.1%**
- overall mean net at 5 bps: **+40.88 bps/trade**
- high-cost (10 bps) median fold net: **+26.29 bps**
- long mean net: **+56.77 bps/trade**
- short mean net: **+22.84 bps/trade**
- strategy median-fold risk-adjusted score: **0.1826**
- equal-timing long-gold risk-adjusted score: **0.2245**

This is rejected because the corresponding state relationship has the wrong sign / inadequate fold breadth and the strategy does not beat the frozen equal-timing long-gold risk-adjusted control.

The |shock|>=1.5 / 10d continuation cell has 135 trades and +23.45 bps/trade, but its short subset is negative and its state rho is -0.0575.

## Decision

**Reject Gold Macro-Shock Event v1.**

Do not reinterpret the attractive 10-day continuation PnL as an edge after the state test failed. Do not retune the same daily composite thresholds or horizons around these outcomes.

The next gold lane should change information structure again: scheduled-event intraday reactions around CPI, FOMC and NFP, using official event timestamps and post-release entries only. This would test a different mechanism—price discovery after discrete information releases—rather than another transformation of daily macro changes.

## Claims

- macro-shock predictive state established: **no**
- executable development edge: **no**
- locked validation opened: **false**
- verified future OOS: **false**
- leverage authorized: **false**
- live enabled: **false**
