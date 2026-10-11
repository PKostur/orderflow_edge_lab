# PSR17 public Negative Volume Index batch 11 preregistration

One new declared eight-hour funded Spot mathematical adaptation of an educational source. No deployed bot or native exchange execution parity claim. Canonical configuration SHA256 `81417317498380c7f4435e54ded6d2d267da0838c16ca1676b599c9f9333310b`. After registration minimum24 trading /25 signal-model cells; attempted remains23/24 until the market run starts. All fourteen fresh tested adaptations remain rejected.

## Source

[Pinned NVI example](https://github.com/cinar/indicatorts/blob/c6bfb623b2ccbac2c536d60740e8c458e4efa7cd/examples/volume/negativeVolumeIndexStrategy.ts), MIT copyright2022-2026TheIndicatorAuthors. NVI initial1000. If previousvolume<currentvolume retain NVI; otherwise update previousNVI+((currentclose-previousclose)/previousclose)*previousNVI. Equal-volume bars update. Source period255 is ignored by NVI and used by its EMA: alpha2/256, beta1-alpha, first seedNVI[0], exact currentNVI*alpha+previousEMA*beta operation order. BUY every NVI<EMA state, SELL every NVI>EMA state, HOLD equality. Preserve this published direction, no textbook reversal or crossing requirement.

Initialize once at retained first closed bar2023-04-01T00Z, then carry through the full history including240bar warmup. Never crop240bars or reset at admission/day/month/year. Volume is Binance Spot base-asset volume summed across480complete minute bars, not quote-volume or trade count. EMA255 is85days at8h, with source first-value seed, no fabricated SMA startup. A future-only protocol must separately declare its carried feature/history and inventory initialization before later observations.

Original pinned TypeScript indicator/EMA/actions and independent scalar calculations matched exactly on8985synthetic rows,22fixtures,10prefixes/5futuremutations. Independent reviewer repeated native execution and original source fingerprints. Draft cash engine independently checked80synthetic paths/88events, including47accepted randomized entries while flat on originalSELL boundaries; zero accounting residual. These are preregistration prerequisites only. Final actual committed evaluator/config review must precede any raw market loading.

## Explicit execution and evidence gates

Source illustrative applyActions begins cash1, buys fullbalance at same signal close and sellsallshares onSELL without fees. Declared adaptation: independent10000USDT ETH/SOL/LINK sleeves, completed8h signals,240bar admission warmup, nextminuteOPEN execution. Decimal(str(cash/(signalclose*(1+sidecost)))) floor8; fixed quantity, all-or-reject without resize/borrow/short/pyramid/partial/orders. HeldBUY countedignored beforeSELL liquidation; no sameboundaryreentry. SourceSELL closes already-held longs at nextOPEN; a randomizedBUY may enter while flat onSELL because no position existed to close. No invented stop/target/trailing/timeout. FundedBTC owns cash/quantity/costs; final inventory is CENSORED_MTM with pendingfinalSELL retained. Eight-hour-close DD is not intrabar risk bound.

Auditable existing continuous Binance Spot BTC/ETH/SOL/LINK panel2023-04-01 through2026-09-30,1,841,760minutes/3837eight-hour bars each; firsteligibleentry2023-06-20T00Z. Quality-only selection, no repairs or2022bear coverage. Spent development evidence, not untouched data.

All20/40/60/80cost cases andtwo gap labels retained; gap histories identical without protection. Shared return, MFE/MAE, fundedBTC, calendar/cluster/session/group/leaveout diagnostics and all frozen gates unchanged. 500entryweek rawBUY-state randomizations preserveweekflagcounts and rerun their own quantities/admissions/endogenous duration against originalSELL-state exits. Seven-bar lag,2000moving4calendar-week blocks includingzeros; fixedalpha.025descriptive carryover foronecell, not global search correction. No history pruning,64/4096capsfailclosed. Exact config is authoritative.

Broad trend/mean-reversion overlap remains; volume-conditioned cumulative path is a distinct source mechanism, not an orthogonality or edge claim. Historical survival only permits separately frozen adequately powered future confirmation, calibrated execution/costs, controls and paper reliability. Viability requires that future confirmation pass. No retuning or candidate rescue.

Fourteen frozen paths plus106prior definitions/artifacts hash-bound. DON8/EMA8/VOL8/DV2/D4/payoff geometry/session watches/frozen prospective protocols preserved. Bollinger excluded. No orders.
