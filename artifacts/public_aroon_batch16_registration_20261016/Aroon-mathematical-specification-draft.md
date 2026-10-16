# Aroon mathematical specification draft

Synthetic preparation only; no registered candidate or market trial. Source selection/readiness and these equations precede KAMA market outcomes. No performance claim or approval for a production candidate.

Pinned source: Hulme-Labs/indicatorgo commit35bd387db11de8e544ad545c68f198677ce4c6b7, strategy/trend/aroon_strategy.go and trend/aroon.go. AGPL original Go/helpers/harness/build remain outside Git under the uploaded specification. Future repository implementation must be independently authored from equations, retaining only URI/hash and numerical provenance receipts. No copied GPL-family source is authorized.

For positive finite raw high H[i] and low L[i] with H[i]>=L[i], let U[i]=max(H[i-24:i+1]) and D[i]=min(L[i-24:i+1]) for i>=24. These raw25 rolling extrema first become available at24. For each i, use the trailing up-to25 already emitted U values, and separately D values; partial prefixes emit immediately, so no second24-bar wait.

For an upper window, find its maximum M. Scan newest to oldest. Count values until an M has been found and the next scanned value is strictly less than M; stop before that less-extreme value. The age is counted_values-1. For the lower window use its minimum and stop at a strictly larger value after finding it. This locates the oldest end of the first contiguous extreme plateau encountered in the reverse scan, retaining any newer pre-extreme observations. It is not a most-recent raw-price argmax/argmin.

For each age a, evaluate sequentially -1*a+25, divide25, multiply100, then round to zero decimal places with nearest-away ties. On this nonnegative integer-age domain, floor(value+.5) implements the rounding. Preserve scalar operation order. Expose Up/Down at raw index24 onward; startup values unavailable. BUY every roundedUp>roundedDown, SELL every roundedDown>roundedUp, HOLD equality. Source stream prepends24 HOLD even with fewer observations; an adapter must expose only actual n available bars, first min(24,n) HOLD, without phantom future slots.

The source's flat Up/Down run is100,96,92,...,4 then4, rather than a textbook constant100. Preserve that behavior. No correction to conventional Aroon, crossing reinterpretation, added threshold, reset or performance-driven source change. It uses high/low and no volume; broad prior trend/range-extreme family overlap remains, with no incremental information claim.

Original educational OutcomeWithContext balance1/shares0 gives same-close cost-free fullcash intent. A future separately declared eight-hour Spot cash study should use the frozen FI/KAMA fee-reserved signal-close floor8 quantity at next minute OPEN, all-or-reject, own funded BTC/cash, no protection/timeout/short/borrow/pyramid/resize/orders. Whole entry-control replacement retains source SELL; own admissions/durations/censoring. No source broker/exchange or live reliability parity is established. Existing historical gates, diagnosticalpha.025, costs, calendar blocks and fail-closed caps remain required. Any historical survivor needs separately frozen untouched future confirmation before viability.

Current evidence is finite synthetic source/helper parity only. Actual candidate/config/simulator/tests and independent review must be frozen before any market data load. No Aroon trial or prospective protocol has been started.
