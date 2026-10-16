# PSR14: source-default Supertrend flip mathematical port

One new registered source adaptation, SupertrendFlip8hDefaultIntent. All numeric rules, prices, costs, controls and gates are in the immutable configuration. This is not native Pine replication. Inspected publisher rahulmr differs from named MIT/commit author Tom Rumpf (tomcru); original publication remains unestablished. Source audit and later primary-reference clarification are both retained. No source code copied; mathematical implementation preserves declared source formulas and operation order.

## Source defaults and exact state

ATR10 uses official v4 reference-equivalent Wilder/RMA: first9 undefined, scalar left-to-right first10 true-range sum /10 seed, then alpha1/10 and beta1-alpha two products plus addition. TR0 high-low; subsequent max of range and gaps from priorclose. Native summation/bit parity is unverified. Midpoint adds high+low then divides2. Basic lower midpoint minus3ATR; upper plus3ATR. Persistent lower uses maximum when priorclose strictly exceeds priorlower; upper uses minimum when priorclose strictly below priorupper. Direction tests currentclose strictly above priorupper first, then below priorlower, else prior direction with initial1 fallback. Undefined comparisons are false; equality does not flip. Only direction transitions enter; initialbullish state and band availability do not enter. Do not substitute ta.supertrend, change factor, or restart state at warmup.

Source market entries reverse inside inclusive2019-01-01 through9999-01-01 date window. UTC Binance calendar adaptation is declared. Long-only Spot closes to cash on originalbearish flip; no short opening. Default optional15%stop stays disabled; plotted trendline is not a submitted stop. No strategy.exit/all-NaN runtime issue, no invented timeout or endpoint liquidation. Still-held inventory is CENSORED_MTM under common cutoff policy.

Source10000USD/5%equity intent becomes10000USDT under1:1 accounting with fee-reserved fixedsignal-close quantity floored8decimals, next-open all-or-reject. This differs from nativeopening-equity sizing and has no nativeconversion/fill parity. Common20/40/60/80bps, fundedBTC, MFE/MAE, session/calendar/cluster/leave-out,500 weekly randomized entries and7bar lag remain. No price barriers: bothgapmodels intentionally coincide. Keep2000 moving4week blocks and fixedalpha.025 conservativecarryover forONE new cell, no global repeated-search claim.

## Readiness, evidence and claims

Same quality-selected2023-04-01 through2026-09-30 complete four-symbol minute panel,240closed8h bar warmup, ETH/SOL/LINK sleeves and BTC reference. Spent development only; no2022bear coverage. Preserve all existingacceptancegates and prior21signal-model/20trading attempted cells. RegistrationaddsONE cell:21registeredtrading/22registeredmodel minimum; do not claim this newcell tested before marketexecution.

An independently validated pre-outcome review binding exactevaluator and canonicalconfig is required BEFORE ANY rawmarketload. If review is unavailable, preparation can continue but outcomes must remain blocked. Full tests/primary reference fixtures cannot substitute for that independent gate. A historicalsurvivor can only begin separately frozen adequatelypowered untouchedFUTUREconfirmation with calibratedcost/execution/paperreliability; viability remains false until confirmation passes.

Bollinger excluded. DON8, EMA8, VOL8, DV2, D4, existingpayoffgeometry, sessionwatches and frozenprospective protocols remain unchanged. No orders, borrowing or parameterretuning. All source/trialhistory remains retained; ATR/trendfamily reuse is explicit.
