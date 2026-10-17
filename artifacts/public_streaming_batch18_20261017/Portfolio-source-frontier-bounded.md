# Bounded portfolio-source frontier

17 October 2026. **Two published stacks retained; neither admitted or registered. Zero new trials.** No market datasets, batch18 outcomes, backtests, external orders or repository edits.

Primary source: [pmorissette/bt](https://github.com/pmorissette/bt/tree/819cd9d3ba612bc29563201417d0bf5c6cc7dda1), pinned commit `819cd9d3ba612bc29563201417d0bf5c6cc7dda1`, MIT, copyright Philippe Morissette. The companion JSON records file hashes and exact class/cell locators.

## Actual published examples

| Stack | Exact source | Rules |
|---|---|---|
| Monthly equal-weight portfolio | `docs/source/intro.ipynb`, code cell5 | RunMonthly → SelectAll → WeighEqually → Rebalance |
| Weekly inverse-volatility portfolio | Same notebook, code cell14 | RunWeekly → SelectAll → WeighInvVol → Rebalance |

The example universe is **SPY/AGG**, obtained by the unexecuted cell3 data-fetch call. Backtest constructors supply no capital, commission or integer-position overrides: library defaults are capital **1,000,000**, commission argument `None`, integer positions enabled.

The inverse-volatility rule uses **three calendar months**, lag **zero**, and per-asset sample-return standard deviation (`ddof=1`). It normalizes inverse volatilities, drops missing weights, gives a lone selected asset 100%, and adds no cap or risk target. A full three-month history is not explicitly required by the source. No trend or momentum entry filter exists in this stack.

`SelectMomentum` requires an explicit `n`. Component defaults therefore do **not** justify inventing a monthly “top one” rotation strategy. No such candidate was constructed.

## Execution and causal boundaries

- Rebalances use **current-row prices** in the native accounting loop. This is not a next-open asynchronous exchange execution model.
- Calendar defaults run on the first actual input date and then period changes. They do **not** run on the last input row, even at a calendar change. A prefix ending there may schedule differently from a longer series. This static finding needs a synthetic prefix test.
- Warmup suppression does not automatically turn research admission into a new source “first date.” Forcing an initial rebalance would be a declared change.
- Source allocation adjusts quantities for integer shares and commission outlay. It is different from the previous drafts' fixed-unit all-or-reject policy. Shared cash, sale/purchase order, lot rounding and failure atomicity need independent proofs.
- The dependency declaration leaves `ffn>=1.1.2` unpinned. Return preprocessing, exact runtime and volatility edge cases remain unresolved for parity.

## What an 8h Spot adaptation would require

Freeze the universe from already available symbols without inspecting returns, disclose replacement of SPY/AGG, define pooled capital, 8h open/close timestamp labels, rebalance clock, next-open funding/lot handling, and matched BTC benchmark/accounting. A 240-bar 8h warmup is 80 days, not necessarily three calendar months. Do not add a completeness rule, weight cap, stop or timeout silently.

A portfolio needs prospectively defined turnover events, dependence clusters, costs and controls. Independent single-symbol sleeves and their trade counts do not automatically define a shared-wallet rotation protocol. Existing frozen lanes must remain unchanged.

These mechanics differ from single-symbol entry rules, but inverse-volatility allocation reuses volatility information already present in prior research. Equal-weight monthly rebalancing is best treated as a portfolio baseline/control; neither source establishes an independent edge.

## Extraction and next step

Inspection selected exact constructor Call nodes and named library methods. No notebook assignments, outputs, performance tables, or result/plot calls were selected, and no data-fetch/backtest call was executed. Prior negative/quarantined leads and the earlier extraction incident remain retained unchanged.

If a separate portfolio lane is chosen, first freeze an own mathematical specification and prove schedule, weight, cash, missing-data and endpoint behavior with synthetic fixtures. No candidate is ready for market evaluation from this source survey alone.
