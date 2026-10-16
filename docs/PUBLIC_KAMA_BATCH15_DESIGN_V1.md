# PSR21 KAMA state cash preregistration

Baseline main `263f3c8ff0dc96b4cbb9b4899e4a56cadd181149`. Canonical config `b5301719ed0aae9129b36573c85264cc91b5412eba695881812f29d17f22f49d`. New eight-hour Spot long/cash mathematical adaptation of the pinned educational source: https://github.com/Hulme-Labs/indicatorgo/blob/35bd387db11de8e544ad545c68f198677ce4c6b7/strategy/trend/kama_strategy.go. Original OutcomeWithContext supplies full-cash intent; no publisher profitability, deployed bot or exchange execution parity claim.

The source is AGPLv3. Original Go/helper/harness/build code remains outside Git. Only URI/hash receipts, synthetic numerical evidence and an independently authored mathematical specification/implementation are retained, as required by the uploaded specification. No GPL-family source copying is authorized.

## Exact source mechanics

ER10, fast2, slow30. Neumaier rolling sum of ten absolute one-bar close changes; add incoming before removing outgoing, ten-slot circular buffer, physical-order recomputation if denominator becomes nonfinite. Seed previous KAMA at close9; first public output at10. Weight=(ER*(2/3-2/31)+2/31)^2 and K=previous+weight*(current-previous), preserving scalar operation order. IEEE0/0 becomes NaN and recursive KAMA remains NaN permanently; no ratio repair, level restart, epsilon or threshold. BUY every close>KAMA, SELL every close<KAMA, HOLD equality or unordered comparisons, not crossing-only. First min(10,n) actual bars HOLD; no phantom short-input slots. Carry full history from2023-04-01 without240/day/trade/session resets. Volume is not part of this source.

See retained mathematical specification and exact config for full equations and attribution. Synthetic native evidence:21 fixtures,4714 KAMA values,4924 original actions;22 unattached short-input padding HOLDs excluded leaves4902 actual-bar actions. Independent feature proof, causal prefixes and future mutations precede this freeze. Finite values/masks match retained fixtures; no all-input or native exchange/broker parity claim.

## Funding, clocks, diagnostics and controls

Three independent10000USDT sleeves. Original source educational accounting uses full cash at same close without friction; declared adapter reserves fees in a signal-close quantity, Decimal floor8, fixed before next minute OPEN, all-or-reject without resize. Own funded BTC cash/notional fraction/quantity/costs. BUY while held counted ignored before SELL; no same-boundary reentry. No shorts, borrow, pyramiding, protection, timeout or orders. Final holdings CENSORED_MTM; final queued SELL remains pending and final flat BUY unexecuted. No asynchronous native broker/failure-recovery parity claim. Eight-hour-close drawdown is not an intrabar bound.

20/40/60/80 nominal round-trip bps on actual entry/exit notionals. Two no-protection gap labels intentionally coincide.500 weekly controls replace the entire BUY qualifier, retain original SELL and own funding/quantities/admissions/endogenous durations. Controls may enter invalid KAMA and persist to cutoff while SELLfalse. Seven-bar lag unchanged.2000 moving four-calendar-week bootstrap blocks include zero weeks; fixed descriptivealpha.025 carryover is not global repeated-search correction.64/4096 history caps fail closed. All return/PF/MFE-MAE/session/overlap/calendar/year/symbol/BTC/leave-out/cost diagnostics and historical gates unchanged.

## Evidence and trial boundary

Binance BTC/ETH/SOL/LINK2023-04-01 through2026-09-30 inclusive,1,841,760 minutes/3837 eight-hour bars per symbol; first eligible2023-06-20T00Z. Quality-only common continuous segment, no repairs, no2022 bear coverage. Spent development history. Broad prior adaptive-average/EMA/trend overlap disclosed; no incremental information or orthogonality claim. Source prepared before Keltner outcomes, no outcome-based tuning.

After freeze minimum28 trading/29 signal-model registered; attempted remains27/28 before first market load. All18 completed fresh adaptations rejected.17 new synthetic tests plus all1161 mandatory repository tests, lint and final exact committed evaluator/config independent review must pass; review must be committed before raw/cache load. Runtime Python3.13.14/NumPy2.2.4/pandas2.2.3/win32 frozen.

Historical survival only permits separately frozen, adequately powered untouched future confirmation with calibrated costs/quotes/execution, controls and paper reliability. Viability requires that future pass. No direction/pair/date/size/cost/gate rescue or retuning.14 frozen paths and239 prior paths preserved. DON8/EMA8/VOL8/DV2/D4/payoff geometry/session watches/frozen prospective protocols unchanged. Bollinger excluded. No live orders.
