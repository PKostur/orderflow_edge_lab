# PSR18 public Force Index batch 12 preregistration

One new declared eight-hour funded Spot mathematical adaptation of an educational public source. Source preparation artifacts were collected on 2026-10-11; actual registration timing is proven by the design commit. Baseline main `8267c6cde0d54476684525f10419c4e6da732282` includes scheduling PR #146 after the published NVI study; its three workflow files are additionally hash-preserved. No native deployed bot or exchange parity. Canonical configuration SHA256 `507bf19e29c64cb6ae732bd05e928517ecd2a0f84a17798c0ec443a324688c26`. Registered minimum25 trading/26 signal-model cells; attempted24/25 until the first market load. All fifteen completed fresh adaptations remain rejected.

## Source and recurrence

[Pinned source](https://github.com/cinar/indicatorts/blob/c6bfb623b2ccbac2c536d60740e8c458e4efa7cd/examples/volume/forceIndexStrategy.ts), MIT copyright2022-2026TheIndicatorAuthors. Period13. Raw `(currentClose-prevClose)*currentVolume`; firstprior=self and raw0. EMA alpha2/14, beta1-alpha, firstseedraw0, currentRaw*alpha+previousEMA*beta in exact order. BUY everyFI>0 state, SELL everyFI<0, HOLD equality. Zero-volume raw0 decays EMA and does not forceHOLD. No crossover, scaling normalization or threshold changes.

Initialize once at retained firstclosed8h bar2023-04-01T00Z, carry fullhistory through240bar admissionwarmup. Never crop rolling240/reset admission/day/year. Volume is summed Binance base-asset minutevolume, not quotevolume/tradecount; eight-hour FI is not an aggregation of minuteFI. Any later futureprotocol must separately preregister its carried history and inventory initialization.

Original pinned TypeScript math/actions and independent scalar calculations exactly matched8985synthetic rows,22fixtures,10prefixes/5futuremutations. Draftcash engine independently checked80synthetic paths/79events/44randomBUYflatSELLentries, zero NAV residual. These prerequisite reviews are not final actualcommittedevaluator approval; committed exact-source/config prereview must precede any rawmarket load.

## Declared cash adaptation and frozen gates

Educational illustrative applyActions uses cash1 and costfree sameclose fullbalance intent. Adaptation: three independent10000USDT ETH/SOL/LINK sleeves, completed8h signal, nextminuteOPEN fixedquantity. Decimal(str(cash/(signalclose*(1+sidecost)))) floor8; all-or-reject without resize/borrow/short/pyramid/partial/orders. HeldBUY countedignored beforeSELL; no sameboundaryreentry. OriginalSELL closes heldlongs nextOPEN; randomizedBUY may enter while flat onSELL since no prior inventory exists toclose. No inventedstop/target/trailing/timeout. FundedBTC owns cash/qty/costs. Stillheld cutoff is CENSORED_MTM, pendingfinalSELL retained, lastflatentryunexecuted. Eight-hourclose DD is not intrabarriskbound.

Existing auditable continuous Binance Spot BTC/ETH/SOL/LINK2023-04-01 through2026-09-30:1,841,760minutes/3837eight-hourbars each, firsteligibleentry2023-06-20T00Z after240closedbars. Quality-only selection/no repairs/no2022bear. Inspecteddevelopment evidence, not untouched.

All20/40/60/80costs, bothgaplabels(oneidenticalhistory without protection), return/MFE-MAE/fundedBTC/calendar/cluster/session/group/leaveout diagnostics and gates unchanged. 500entryweek rawBUY-state randomizations ownadmissions/quantities/cash/endogenousdurations against originalSELLexits. Sevenbarlag,2000moving4calendarweekblocks inclzeros; fixedalpha.025 descriptivecarryover1cell, not globalsearchadjustment. 64/4096caps failclosed; nohistorypruning. Exactconfig authoritative.

Constantvolume FI collapses to scaled EMA13 close-difference momentum. Broad prior trend/volume overlaps disclosed; no orthogonality, incremental-volume forecast or independent-edge claim. Source selected for explicit distinct executable recurrence, without performance-based selection. A historical survivor only permits separately frozen adequately powered untouchedfuture confirmation with calibratedexecution/costs/controls/paperreliability. Viability requires that futureconfirmation pass. Closedversions stayrejected; norescue/retuning.

Fourteen frozenpaths and139priordefinitions/artifacts hash-bound. DON8/EMA8/VOL8/DV2/D4/payoffgeometry/sessionwatches/frozenprospective protocols preserved. Bollingerexcluded; noorders.
