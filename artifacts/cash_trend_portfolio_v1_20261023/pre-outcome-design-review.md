# Weekly multi-horizon trend/cash proposal: pre-outcome validity review

Status: mechanically definable new own research adaptation, subject to the execution precision contract below. This is a bounded proposal review, not a performance or production approval. No market prices, PnL, cache, or prior strategy results were loaded for this review. No repository files or frozen protocols were changed.

## Rules reviewed

Four fixed Spot assets: BTC, ETH, SOL, LINK, synchronized eight-hour bars. For completed close C[i], average the signs of C[i]/C[i-L]-1 for L=90,270,1095, then clip below zero. A zero return has sign zero; keep denominator three. Volatility uses the last180 log returns, sample standard deviation ddof=1 times sqrt(1095). Weight per asset is .25*score*min(1,.10/vol); zero volatility gets factor one. Invalid/incomplete history gets zero target without reallocating its sleeve. Valid synchronized positive finite input prices are mandatory for all four; invalid input aborts the study rather than deleting an inconvenient asset/time.

The Sunday16:00-labelled bar completes Monday00:00 UTC. The signal is calculated at that close. Execution is deliberately Monday08:00 OPEN, an eight-hour delay. This is two bar-open indices after the signal bar, not the immediate next bar OPEN. No Monday00-to08 price may affect the frozen signal or desired quantities. Initial wallet is10,000 USDT, cash yield zero unless separately declared.

Desired quantities use signal-close NAV and signal closes. At execution sell excess inventory first, capped by actual holdings; deduct costs; buy remaining deficits with a common pro-rata reduction if cost-inclusive funding exceeds cash. Targets cap each asset at25% at decision; holdings may exceed that after price drift or at delayed execution. No hard continuous exposure or drawdown cap is established. No leverage, shorts, new stop, or favorable redistribution.

## Practical completion before outcomes

1. Specify quantity precision, rounding order, cost arithmetic and the treatment of signed zero/tiny negative cash before the first run. A useful contract is flooring desired and funded quantities to a fixed precision, leaving residual cash; do not silently round up or clamp a materially unfunded debit. Decimal wallet arithmetic is an option, not an adopted requirement here. Freeze how cumulative rounding residuals are handled and test exact-boundary cases. Pro-rata buys must be simultaneous in intention and independent of symbol iteration order.
2. Encode the delay by timestamp assertion: signal Monday00, fill Monday08. Never accidentally fill Monday00 or allow Monday08 CLOSE into the decision. Freeze missed/delayed/missing execution handling and final pending-order/censor treatment. Rebalance desired quantities once per signal; no intrawindow updates or daily volatility re-sizing.
3. Index the year return using1096 closes and the volatility using181 closes. Admit a common portfolio only after the fixed longest history is available; retain an initial cash-only period or explicitly report its exclusion. Do not opportunistically change the denominator, lookbacks, start, assets, volatility floor, or weekly schedule.
4. Baseline20bps each traded side and stress40bps each side mean40/80bps round trip on equal notional. Charge actual traded notional for each partial rebalance, not full NAV every week or only net portfolio flow. Declare whether the single burden represents fee/spread/slippage together. Record all fills, turnover, cash, inventory and marked NAV. Do not call the .10 volatility scaling a guaranteed10% portfolio volatility or loss limit.

## Minimum useful synthetic evidence

- Known return-sign vectors including exact zeros;180-return ddof1 calculation, zero-volatility cap and warmup off-by-one.
- Monday/year/timezone clock fixtures and an explicit two-index delay assertion. Perturb every price after each signal and prove its features/target quantities unchanged; perturb execution OPEN and verify fills/funding change, not prior targets.
- Initially all cash; fully invested sell-to-cash; mixed sell/buy rebalance; large gap up/down; common pro-rata shortfall; precision-edge and nonfinite inputs; no negative inventory/cash or leverage; asset-order permutation invariance.
- Independent per-fill cash conservation and full-wallet NAV; no double counting sell proceeds; repeated flat target incurs only required trades; final signal without fill is pending, not profit.
- Both costs use the same frozen signal decisions. Independently reconstruct all held assets and funded benchmark wallets. If controls are run, repeat the complete funded shared-wallet path for each; do not shuffle completed trade returns as an execution substitute.

## Interpretation and reporting

The2020-08-11 through2026-09-30 panel is spent development evidence. Freeze this one version without parameter search. Report net total return/CAGR, maximum drawdown and recovery, yearly results, turnover/costs, exposure/cash and asset contributions against separately defined cost-matched passive BTC and fixed-universe allocation controls. These are descriptive comparisons; the portfolio is one dependent system, not four independent successes. Do not inherit single-symbol trade-count gates as validated portfolio gates, or alter their frozen definitions.

No test here establishes profitability. A new immutable candidate ledger must distinguish this own adaptation from prior public-source versions. Any confirmation begins after its actual freeze and before observation of the eligible future window; untouched cannot be inferred merely from dates later than September30. Candidate-specific finite endpoint, uncertainty/dependence/power, global attempt accounting, controls and paper reliability must be fixed separately. Previous rejected candidates and existing prospective protocols remain unchanged. No live route is authorized by this review.
