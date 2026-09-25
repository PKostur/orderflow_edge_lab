# Payoff Geometry v1.1 (`universal-payoff-geometry-diagnostics-v1`)

Historical, descriptive, non-gating. Same frozen window as v1 (2024-01-01 to
exclusive 2026-09-12). It feeds no filter, Jev decision, threshold freeze or
promotion gate, and emits no cell ranking.

## Relationship to v1

v1.1 is an additive extension of `payoff_geometry_v1`. It reuses the v1 episode
reconstruction (`enrich_trade_geometry`), the canonical MFE/MAE reconciliation
and the frozen 71-cell grid unchanged. v1 artifacts and conclusions are not
modified. v1.1 adds:

- `bars_to_mfe`, `bars_to_mae` and `excursion_order`
  (`MFE_FIRST | MAE_FIRST | SAME_BAR | NO_MFE | NO_MAE | NONE`). `SAME_BAR` is
  reported as unobservable from OHLC and is never resolved by assumption.
- `static_gross_bps`, `capture_ratio` and `giveback_bps`, all on the same
  fixed-entry-price convention as MFE (see the accounting note below).
- A hard ledger reconciliation: every completed episode's canonical
  `gross_bps` must equal the open-to-open bar path to 1e-6 bps.
- A strategy × direction (ALL / LONG / SHORT) × cell split.
- Per cell: raw N, Kish effective N over 30-day calendar blocks, `sufficiency`
  (raw N ≥ 20), `effective_n_sufficiency` (effective N ≥ 20), top-decile share
  of gross profit, skewness of net bps, p10–p90 distributions, and deltas
  versus the same strategy × direction `ALL` cell for win rate, expectancy, MFE
  and net quantiles.
- A Politis-Romano stationary bootstrap over UTC calendar days (mean block
  length 30 days, circular, 500 replicates), shared across all symbols,
  strategies, directions and cells within each cost case. It produces
  descriptive intervals only, with no p-values.

Open episodes at the snapshot end are right-censored. They are excluded from
every cell and counted per strategy × direction.

`effective_n_sufficiency` was added after the first run, which showed
effective N of about 16–31 even for cells with thousands of trades. It can only
downgrade a cell.

## First local run (20 bps; counts match v1)

| Strategy | Dir | N | Eff. N | Win | E[net] bps | 95% stationary CI | Median MFE | Median giveback | Top-10% profit share | Skew |
| --- | --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: |
| DON8 | LONG | 108 | 16.0 | 34.3% | 1,060 | −561 to 2,749 | 1,277 | 2,519 | 0.78 | 3.7 |
| DON8 | SHORT | 112 | 16.8 | 36.6% | −108 | −715 to 627 | 2,212 | 2,029 | 0.59 | 1.1 |
| EMA8 | LONG | 160 | 17.4 | 24.4% | 621 | −445 to 1,908 | 829 | 1,540 | 0.86 | 5.1 |
| EMA8 | SHORT | 172 | 18.6 | 26.2% | −87 | −455 to 340 | 992 | 1,462 | 0.70 | 2.0 |
| VOL8 | LONG | 978 | 28.9 | 36.0% | 112 | −23 to 296 | 234 | 381 | 0.87 | 12.1 |
| VOL8 | SHORT | 1,117 | 28.7 | 33.2% | −33 | −107 to 56 | 237 | 382 | 0.79 | 2.3 |

Every interval includes zero. In the ALL-direction cells, effective N is 24.1 of
220 (11%) for DON8, 22.9 of 332 (7%) for EMA8, and 30.9 of 2,095 (1.5%) for
VOL8. VOL8's `SAME_BAR` share is 37%, so MFE-versus-MAE
ordering for VOL8 is unobservable for more than a third of its episodes.

## Accounting note: short-side convention in canonical v2

`_canonical_trade_ledger` compounds `Π(1 + pos_t · r_t)` over open-to-open
returns. For a ±1 long this equals `exit/entry − 1`, which is a fixed-quantity
position. For a ±1 short it equals `Π(1 − r_t) − 1`, which is a constant-notional
short rebalanced every bar. The implied rebalancing turnover is not charged. A
fixed-contract futures short earns `1 − exit/entry` instead, which is the same
convention as the ledger's MFE/MAE.

The measured gap (ledger minus static) on completed shorts at 20 bps:

| Strategy | p10 | p50 | p90 |
| --- | ---: | ---: | ---: |
| DON8 | −1,029 | −244 | 203 |
| EMA8 | −758 | −72 | 74 |
| VOL8 | −89 | 0 | 4 |

Long/short asymmetry in any canonical-ledger result is therefore partly an
accounting convention for the slow strategies. v1.1 does not modify the frozen
canonical accounting. Capture and giveback use the static convention so that
they are commensurable with MFE, and the gap is reported per strategy. Deciding
which convention is canonical needs its own versioned accounting change.
