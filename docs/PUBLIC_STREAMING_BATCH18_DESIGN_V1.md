# PSR24 streaming reversal synthetic design record

This new design registration describes own mathematical reference implementations of two fixed public source strategies. No market/raw/cache loader or study registration exists in the draft. Actual registration requires independent full prototype review, verified PR172 publication, a new design commit, a clean-checkout evaluator/test installation, tests/lint, and independent approval binding the exact committed evaluator and canonical config before first market load.

## Primary sources and unchanged signal/size choices

Quickstart06: official backtrader-docs e20cea18b88e1693b65e408f8778cc076ab21a67/docs/quickstart/quickstart06.py, source47b82d6ae2e3940bff80450e8c17a7074204c1f7ff70f7e56a25fe0e988e0d4c. Two strict falling closes C0<C-1<C-2. Fixed one unit. Actual filled OPEN E establishes its source clock; decision at close E+5, exit next OPEN E+6.

UpDown40: cloudQuant/backtrader b418caf7364e1134983a4c4b394768686e1916aa/tests/strategies/test_85_up_down_candles_strategy.py, source35b643f11fb5aba0041fae5ae19ab3a8bf312865ef9be126ab8cfb2c181b45e4. (C0-C-40)/C-40 strict < -0.01 enters, >= +0.01 exits. Fixed ten units; strength unused. Source flat shorts explicitly refused for the declared Spot longcash adaptation. No sign-zero substitution. Price reversal family overlap disclosed; no orthogonality claim.

## Causal/source distinction

Default preloaded native startup failures remain retained; unchanged default publisher bot is not represented as causal. Separately declared preload=False/runonce=False source-class receipts are synthetic and bounded. A common research cash origin is closed feature index239 after240complete8h candles, earliest OPEN240; initially flat/nopending. No startup trades, feature/trade/day/session resets, shorting, borrowing, pyramiding, protective stop, new timeout or sameOPEN exit/reentry. Original source cash100000 and source friction unset/0.1percent differ from research sleeves10000 and cost policy below. Do not increase cash or resize quantities to prevent rejection.

## Literal funding, orders and benchmark

Three10000USDT sleeves per candidate, not pooled across candidates. At source decision close create a fixed-unit request. Native checksubmit=True funding must pass at created-close price, then at next OPEN. Each debit is notional=q*P; cash=cash-notional; cash=cash-notional*side. Credit cash+=notional then cash-=notional*side. Float64 operation order preserved. Exactzero/signedzero accepted; any source debit<0 receives that stage's Margin. No clamp, tolerance, resizing or retry until a later eligible source close.

BTC is a separate reference wallet with its own cash/quantities, not upstream native hedge parity. Accepted source notional/prebuy cash fraction determines BTC owncash*fraction/BTCOPEN units, then its own literal fee debit. Every negative or nonfinite BTC debit, even floating residual, aborts the complete evaluation including controls failclosed; never omit benchmark leg or prune only the failing history. This deliberately differs from earlier shared1e-8 tolerance/clamp and is fixed before market data. Independent concrete unmocked negative-rounding regression retained.

Atomic full nextOPEN fills are hypothetical reference execution. Partial fills, delayed/asynchronous callbacks, cancellation races, generic external Rejected, lot/tick/minimum rules, depth/liquidity and exchange order routing are unmodeled/failclosed; no parity claim. Pending lock excludes duplicate intent; final queued entry has no fill, final queued exit leaves separate CENSORED_MTM inventory. Cutoff is a known-close mark including hypothetical liquidation burden, never a fictitious completed exit. Funding rejection does not debit BTC wallet.

## Fixed costs, controls, reporting and gates

Nominal roundtrip20/40/60/80bps means side=cost/20000 on actual entry/exit notionals once. No-protection gap labels intentionally coincide. Own funded cash/NAV and BTC same-exit values, source order/availability/entry/exit clocks, gross/net/PF/MFE/MAE, completed/alladmission populations, cutoff/pending/reject accounting, weekly clustering, UTC clocks, groups, leave-outs and cost stress remain required. Shared descriptive method from before EMV is frozen before this draft's first market load; no strategy/gate rescue.

500within-entryweek whole rawqualifier randomizations retain fixed source sizes, two-stage funding, flat guard, own admissions and endogenous duration: Quick controls use their actual fill E+6, never observed baseline durations; UpDown original exits remain. Sevenbar lag similarly retains own source clock/funding. 2000moving4calendarweek blocks including zero weeks, alpha0.025 per candidate descriptive; no global repeated-search correction. All historical gates unchanged, history caps64/4096 failclosed without pruning.

Before registration attempted counts remain30trading/31signal-model, zero new cells. Two future registered cells would give32/33; attempts increase only at first market load. Historical data remains spent development, not untouched evidence. Any historical survivor requires separately frozen adequately powered untouched future-only confirmation, calibrated execution/cost/quote/control and approval-bound paper reliability. Viability remains unproven until that future pass. No retuning, direction/pair/date/size/cost/gate rescue. No orders. Preserve all frozen lanes and exclude Bollinger.

## Synthetic evidence

Final standalone proof retains15tests, both candidates through all8cost/gapcases,500controls each and2000bootstrap draws/case.18nativefixtures/74fills have exact fill bars/unit quantities; maximum native average-price difference1.4210854715202004e-14 within declared1e-10 bound.18independent scalar fixture cash/state comparisons and own BTC manual accounting/NAV residual0. Default CI smoke may use3synthetic repetitions/64draws in a copied synthetic spec only; hard assertions retain production500/2000 and the standalone full proof. Original GPL source/framework/harness stay outside Git; only own helper, equations, source URI/hash and numeric receipts may enter a future registration.

## Immutable design identity

Baseline main `de9ea155060eeb9390c118dce61f301e5cde6a6a`; canonical config `28deca87c0c3fc03c1c3153f82b12b94dda85891a280962694aea33c1af74936`. Independent draft audit `3bd6208d5584c7a52b02f98cd032de0f8594e90818508906f97d0661cd770a9b`. Registered minimum32trading/33signal-model cells; attempted remains30/31 before first load.14frozen and370prior paths verified exact. Design and evaluator commits are bound separately; final actual committed-source independent approval remains mandatory before any market load. All native source/framework/harness stay outside Git.
