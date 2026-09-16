# Discovery v2 Sprint 1 — Implementation Contract

Status: **locked before any Sprint 1 result is run or inspected**.

The immutable search-space contract is `config/discovery_v2_sprint1_v1.json`; its first-commit SHA is `e228b3ffed6861db8aad2c5808806d1ad2fb73b9`.

This file resolves implementation details that were deliberately not numeric in the protocol. It may not be changed in response to Sprint 1 outcomes.

## Economic observation units

- `dispersion_conditioned_xs_momentum`: one completed scheduled 7-day rebalance/holding block. Daily subreturns are compounded inside the block before statistical evaluation.
- `funding_extreme_reversal`: one completed funding-to-next-funding portfolio interval, clustered across all simultaneously active symbols.
- `btc_residual_shock_reversal`: one completed next-open to following-open one-day portfolio holding interval.

Family-selection diagnostics use aligned portfolio observations, not individual coin legs. Symbol legs are retained only for concentration and leave-one-symbol-out diagnostics.

## Causal timing

- Daily close information at day `t` may first affect positions at open `t+1`.
- Rolling medians, means, standard deviations and BTC regressions use only observations strictly before the completed observation being classified, except for the completed current-day return used as the signal itself.
- A realized funding rate at settlement `t` can be used only after `t`. The position is entered at the first available 1-hour MEXC candle open strictly after `t` and is closed/recomputed at the first 1-hour open strictly after the next funding settlement.
- The funding cash flow credited/debited during that holding interval is the rate at the *next* settlement. It is never used to form the entry signal.

## Costs

- Baseline round-trip friction is 20 bps of gross notional.
- Daily/rebalance strategies apply 10 bps per side to actual portfolio turnover, including transitions to or from cash. Only fully completed economic observations are evaluated.
- Funding-event trades charge 20 bps round trip to each active interval because each signal interval is explicitly opened and closed.
- Stress cases multiply transaction friction only: 1.0x, 1.5x, 2.0x. Historical funding cash flows are not multiplied.

## Survival definitions

A family is `REPLICATION_PENDING` only when every frozen requirement is met.

1. **Variant breadth:** at least 3 of the 4 preregistered variants have positive mean net return at 1.0x friction.
2. **Contiguous cost neighborhood:** at least two adjacent parameters in the preregistered order have positive mean net return at 1.5x friction.
3. **Control weakness:** the median mean-net result across the four candidate variants exceeds the principal reversed-direction control by **at least 5.0 bps per economic observation**.
4. **Validity:** all timestamp/chronology/funding/data checks pass.
5. **Cross-sectional concentration:** any variant eligible to be selected must retain positive mean net return after removing each symbol's contribution in turn. The selected variant must also respect the Discovery v2 concentration thresholds where computable.
6. **Selection diagnostics:** DSR-style, CSCV/PBO and family Reality-Check-style diagnostics are reported for the four-variant family. During cheap falsification they are evidence, not a standalone rescue path; failure of the hard economic/control/concentration conditions cannot be offset by a statistical score.

## Stable selection rule

If multiple adjacent variants survive, take the median parameter among the largest contiguous surviving neighborhood. For an even-size neighborhood, choose the more conservative longer lookback. Never choose an isolated peak or the highest historical PnL simply because it is highest.

## Controls

- Dispersion momentum principal control: reversed winner/loser direction using the selected candidate's same dispersion gate and timing. Ungated 30d/7d dollar-neutral momentum is a benchmark, not a tunable sibling.
- Funding principal control: same settlement timestamps and threshold events with direction reversed.
- BTC-residual principal control: same residual rankings and timing with direction reversed (residual momentum instead of reversal). Raw-return reversal is a secondary benchmark.

## Result-state boundary

A Sprint 1 result can end only as:

- `FALSIFIED`, or
- `REPLICATION_PENDING`.

No result from this D0 sprint can become `ENGINE_REPLICATED`, `LOCKED_VALIDATION`, `PROSPECTIVE_SHADOW`, or live-eligible without a new candidate freeze and the later Discovery v2 stages.
