# PSR20 Keltner one-unit long/cash preregistration

Baseline main `d76882adeb37e7d59bd483d3e07dee7969832dd3`. Canonical config `c12cd30b0eb5ad567e745572d51b8b5f285c50c0288af01c08b617f4badc141e`. New declared eight-hour Spot long/cash mathematical adaptation of [the pinned source](https://github.com/ali-azary/Algorithmic-Trading-From-Beginner-to-Advanced/blob/945c7c430c799687be17092eaebcad6baace1a9e/codes/KeltnerBreakoutStrategy.py). Original two-sided class and default unit size were exercised with a synthetic native broker. No published bot profitability, native Spot execution parity or live reliability claim. README Code MIT statement is bounded: no standalone notice received and placeholder remains; no invented copyright holder/date. No PDF content used.

## Source rules and clock

EMA30 uses arithmetic mean of closes0..29, then previous*(1-2/31)+current*(2/31). Wilder ATR7 uses true ranges1..7 and arithmetic mean seed, then previous*(1-1/7)+currentTR*(1/7). True range is max(current high,prior close)-min(current low,prior close). Effective strategy ATR7 overrides indicator default14. Channel=EMA plus/minus one ATR. Preserve scalar operation order and full-history recursive carry from2023-04-01 through240 admission bars; no rolling-window/day/session/trade reset. Strict comparisons preserve even tiny EMA roundoff on flat prices; no epsilon or rounding repair.

At completed bar i, flat long entry checks close[i-1]>upper[i-1]. Breakout at j is checked after j+1 completes, and earliest reference fill is open j+2. Do not remove this extra bar. Held long exits when current close<current EMA30, separately from prior-bar short entry. Simultaneous flat entry/current exit enters and waits for a later boundary; held status is fixed before action. Full original also shorts; explicitly excluded from this new Spot scope.

## Funding and controls

Three10000USDT sleeves, exactly one base unit. Price-dependent exposure, not equal risk. Whole fee-inclusive debit at next minute OPEN, all-or-reject; no resize, borrowing, pyramiding, shorts, partials or orders. Own funded BTC cash/quantity/notional fraction/costs. Reference filled-next-open exit; no asynchronous broker queue or failure recovery parity. No stop, target, trailing stop or timeout. Final held inventory CENSORED_MTM, final queued exit pending and final flat entry unexecuted. Eight-hour-close drawdown is not an intrabar bound.

20/40/60/80 nominal round-trip bps split across actual entry/exit notionals. Two registered gap labels coincide without protective prices.500 weekly controls replace the entire delayed entry qualifier and rerun own funding, admission, quantity and endogenous duration with unchanged current EMA exit. Seven-bar lag uses the same convention.2000 moving four-calendar-week bootstrap blocks include zeros; alpha.025 is descriptive carryover, not global repeated-search correction.64/4096 history caps fail closed without pruning. All return/PF/MFE-MAE/session/overlap/calendar/symbol/BTC/leave-out/cost diagnostics and historical gates remain unchanged.

## Evidence boundary

4090 native synthetic channel rows/271 unit advices,16 fixtures,7 prefix and3 future-mutation checks match exact scalar port. Independent draft cash review and18 synthetic tests precede this freeze. Required1144 repository tests, lint and final exact committed config/evaluator independent review must pass, with the review committed before any raw/cache market load. Frozen production runtime is Python3.13.14/NumPy2.2.4/pandas2.2.3/SciPy1.15.2/win32; SciPy is retained in runtime identity but not used in Keltner feature math.

Other bounded source-readiness audits are retained with zero additional market trials. OBV remains unselected pending callback lifecycle specification; indicator-offset dependence alone does not prove changed strategy signals. KAMA has source-level synthetic math evidence only. Its AGPL source/build/harness remain outside Git under the original uploaded specification; only URI/hash provenance and synthetic numerical receipts are retained here. Any future implementation must be independently authored from mathematical specification without copying that GPL-family source. No KAMA Spot candidate or production approval.

Binance BTC/ETH/SOL/LINK2023-04-01 through2026-09-30 inclusive,1,841,760 minutes/3837 eight-hour bars each; first eligible2023-06-20T00Z. Quality-only shared continuous segment, no repairs, no2022 bear coverage. Already-inspected development data. Broad prior EMA/ATR/trend/breakout overlap remains; no orthogonality or incremental information claim.

After freeze minimum27 trading/28 signal-model registered; attempted remains26/27 before first market load. All17 completed fresh adaptations rejected. Historical survival only permits separately frozen, adequately powered untouched future confirmation with calibrated costs/execution, controls and paper reliability. Viability requires its pass. No rescue of rejected versions, pair/date/direction/size/threshold/cost/gate tuning.

14 frozen paths and202 prior paths hash-preserved. DON8/EMA8/VOL8/DV2/D4/payoff geometry/session watches/frozen prospective protocols unchanged. Bollinger excluded. No live or exchange orders.
