# Canonical accounting version 3

`orderflow_edge_lab.canonical_v3.run_canonical_backtest_v3` holds the traded
quantity fixed until the strategy target changes. Version 2
(`run_canonical_backtest`) resets exposure to the target weight at every bar.

| | v2 | v3 |
| --- | --- | --- |
| Position between target changes | weight reset every bar | quantity held; weight drifts with price |
| ±1 long episode gross | `exit/entry − 1` | identical |
| ±1 short episode gross | `Π(1 − r_t) − 1` (constant notional, rebalancing uncharged) | `1 − exit/entry` (fixed contracts) |
| Trades | every bar for fractional targets | only when the target changes |
| Exit cost | on target weight | on the drifted weight actually closed |

Everything else is the same as v2: next-open execution, terminal liquidation at
the last observable open, exit-before-entry event order, proportional turnover
costs, unweighted MFE/MAE, exact ledger/equity reconciliation, and rejection of
non-positive equity (a short whose price more than doubles raises instead of
being modelled).

## Status

- v2 remains the canonical accounting for every frozen protocol, and none of
  them is re-bound. `claims.supersedes_v2_for_frozen_protocols` is `false`.
- Adopting v3 for a protocol requires a new protocol version that names
  accounting version 3 before any of that protocol's new evidence is viewed.
- `short_convention_comparison` charges exit costs on the entry notional, which
  is an approximation. v3 is exact; the two differ by well under 1 bps per trade.

## Frozen-window effect (2024-01-01 to 2026-09-12, 20 bps, completed trades)

| Strategy | Dir | N | v2 E / PF / win | v3 E / PF / win |
| --- | --- | ---: | --- | --- |
| DON8 | LONG | 108 | 1,060 / 2.22 / 34.3% | identical |
| DON8 | SHORT | 112 | −108 / 0.87 / 36.6% | 248 / 1.35 / 47.3% |
| DON8 | ALL | 220 | 466 / 1.55 / 35.5% | 647 / 1.82 / 40.9% |
| EMA8 | SHORT | 172 | −87 / 0.86 / 26.2% | 157 / 1.30 / 33.1% |
| EMA8 | ALL | 332 | 254 / 1.43 / 25.3% | 380 / 1.70 / 28.9% |
| VOL8 | SHORT | 1,117 | −33 / 0.82 / 33.2% | −8 / 0.95 / 35.7% |
| VOL8 | ALL | 2,095 | 35 / 1.20 / 34.5% | 48 / 1.28 / 35.8% |

Mean per-symbol total return: DON8 0.56 → 1.20, EMA8 0.46 → 1.16, VOL8 0.28 → 0.72.

This is same-period development evidence. Payoff geometry v1.1 reports
stationary-bootstrap intervals that span zero and effective N of about 23–31.
v3 changes how shorts are scored, not the strategies' evidentiary status.

## Version 3.1: funding

Pass `funding=` (raw settlement rates indexed by settlement time, for example
from `basis_convergence.fetch_mexc_funding_history`) to
`run_canonical_backtest_v3`. The accounting version becomes `"3.1"`.

- Settlement rates in `(open[t-1], open[t]]` are summed onto `open[t]`
  (`align_funding`). This handles 8h, 4h and 1h schedules the same way.
- The position held into `open[t]` (drifted weight, before any trade at that
  open) pays `weight × rate`: longs pay positive rates and shorts receive them.
  A position opened at `open[t]` does not pay the settlement at `open[t]`. The
  terminal open settles before liquidation.
- Each trade carries `funding_bps`, the additive sum of its cash flows. Its
  `net_bps` compounds funding with price and costs, and the ledger still
  reconciles exactly with equity.
- Missing settlements count as zero and are reported as
  `accounting.funding_coverage`, never silently imputed.
- With `funding=None` the result is identical to v3.

Crypto check (frozen window, 30-sleeve portfolio, 20 bps): funding drag is
1.0%/yr over 2025-04 onward, where MEXC history exists; Sharpe goes from 1.07
to 1.06. On MEXC tradfi perps funding is 10–84%/yr in absolute terms (see
`PORTFOLIO_ANATOMY_2026_09_26.md`), so any tradfi protocol must use v3.1.
