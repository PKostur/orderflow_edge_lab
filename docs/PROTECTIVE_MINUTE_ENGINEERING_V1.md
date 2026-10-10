# Protective minute engineering v1

This is a prerequisite for the two queued public sources, not a strategy screen.
No new strategy market outcomes, trading cells, orders, future watch or candidate
promotion are produced. The six prior adaptation rejections remain closed. The
user's completion criterion requires confirmation on genuinely untouched data
collected after the eventual candidate freeze. There is currently no survivor.

## Sources and compatibility

- [MAGen source](https://github.com/jesse-ai/example-strategies/blob/7c91e0a37bf62165790120d730442e4f6eb00364/MAGen/__init__.py), MIT,
  SHA256 `4e54ad4d8051900bda92e477fc997d67a4fb7b930f8025fb6f087116488b0316`.
- [Ichimoku source](https://github.com/pcjtse/trading-view-strategies/blob/7b03cff0d80ebd048c8e94d452fd797a8f4b973f/strategies/ichimoku.pine),
  license unestablished, mathematical inspection only, SHA256
  `8b7827436d1604e89c390b18017eefb4b199ceb8d8bf64e5cf99c859cb517d5c`.
  No upstream code is copied into this change.

MAGen's pinned [sizing implementation](https://github.com/jesse-ai/jesse/blob/417f8765225e3bfc12043d4b712f19fe15a3c078/jesse/utils.py#L149-L210)
already caps position notional at capital. Its omitted fee argument defaults to
zero. A fee reserve and rejection of an unaffordable next-open fixed quantity
are declared adaptations; source sizing is not intrinsically leveraged.
Protective orders assigned inside `go_long` fail the pinned current Spot
framework path. A compatible lifecycle port would also be an adaptation, not
an unchanged native strategy run.

Neither source enforces a timeframe or supplies an administrative 30-bar exit.
An eventual eight-hour signal study needs its own pre-outcome design. Do not
import the rejected batches' timeout into these sources silently. Default Pine
bar ordering, execution properties and native UI overrides are distinct from
the conservative model below. See [Pine v5 strategy execution](https://www.tradingview.com/pine-script-docs/v5/concepts/strategies/).

## Implemented primitives

`src/orderflow_edge_lab/protective_minute.py` is an offline pure library. It has
no signal generation, network access, broker client or order transmission path.

1. Minute OHLC and bracket inputs require finite positive prices and aligned UTC
   integer minute epochs. Decisions cannot activate protection retrospectively.
2. Resolve a previously scheduled market exit at the next open before using that
   minute's later high/low. Both reference prices and exit clock are explicit.
3. An active stop crossed by an opening gap references the adverse open, not the
   stop level. An opening gap above a target keeps the target as the conservative
   price and the open as price-improvement sensitivity.
4. One touched barrier uses its reference level. Both touched barriers retain
   stop-first and target-first price bounds. Within-minute ordering and exact
   timestamp are unknown; retain the half-open minute interval.
5. A completed-minute bracket replacement applies only to later minutes. It may
   lower a stop; there is no invented monotonic trailing rule.
6. Risk sizing computes a cash-capped base quantity at signal close, reserves a
   declared entry burden and rounds down to eight decimal places. The fixed
   quantity is accepted or rejected at the next-open reference; no future-price
   resizing or borrowing is introduced. Zero quantity is rejected without cost.
7. Entry/exit cash charges use actual modeled notionals. Defaults of 20 bps per
   side represent assumed fee plus friction, not measured historical execution.
   Finite-input overflow in derived financial values is rejected.
8. BTC excess uses the same exit minute. Opening exits use BTC's opening price;
   intraminute exits use BTC low/high reference-return bounds, subtracting the
   opposite bound for excess. A full eight-hour BTC close cannot substitute.
9. MFE/MAE require the complete held-minute prefix beginning at the known entry
   open. Exit-minute extremes are outer bounds, not necessarily pre-exit prices.
   An open exit ignores later extremes entirely. Missing, duplicate, reversed,
   leading-omitted and post-exit minute inputs are refused.

These bounds describe the stated OHLC touch model. A touched price does not
prove limit queue execution or stop fill liquidity. Neither bound guarantees a
real executable result. A BTC reference-return bound is not a cash-reconciled
benchmark portfolio. Exchange lot sizes, minimum notionals, historical fees,
quotes, depth, latency and partial fills remain uncalibrated.

## Pinned indicator audit

The isolated official Windows CPython3.13 `jesse-rust==1.3.0` wheel SHA256 is
`5e29ad2a2388e714239781ecf77ecd001dadc47026c6c64dd46891f5e309ce1b`,
previously checked against [official release metadata](https://pypi.org/pypi/jesse-rust/1.3.0/json).
Rust source tag resolves to `65e1007faf1804ca66651bc76cccd3feb80a0d6d`;
Jesse framework is pinned to `417f8765225e3bfc12043d4b712f19fe15a3c078`.

Independent ATR32, scalar ATR32, ADX8 and linear-regression5/20 formulas matched
16 synthetic fixture cases and 16 rolling240-window cases. Maximum absolute
error was `1.2789769243681803e-13`, below the fixed `1e-9` tolerance. Seed NaN
placement matched. Rolling native-window ATR differs from a continuously
updated ATR; the latter cannot silently replace it. Linear-regression input is
contiguous float64. A direct strided view panicked and is not audited support.
The rerunner checks the installed wrapper and binary against pinned wheel bytes.

This is kernel parity on one recorded runtime, not cross-platform strategy,
fill or risk parity. No dependency is added to the package or CI. Original and
reproduced reports are retained under `artifacts/protective_minute_engineering_20261011/`.

## Verification and rerun

The synthetic tests cover gaps beyond both barriers, both touches, inactive
protection, next-open close precedence, bracket update causality, cash and fee
rejection, reconciliation, synchronized BTC bounds, excursion uncertainty and
numeric overflow. They do not test a complete position lifecycle or any strategy
against market data.

```powershell
$env:PYTHONPATH='src'
python -m unittest discover -s tests -p test_protective_minute.py -v
```

Optional native audit, with the pinned wheel installed/extracted in a separate
directory and NumPy available on the recorded Windows Python3.13 runtime:

```powershell
python scripts/audit_magen_native_indicators.py --runtime ../magen_native_runtime --wheel ../magen_native_wheels/jesse_rust-1.3.0-cp313-cp313-win_amd64.whl --output native-indicator-audit.json
```

## Next required study

Before opening any new market outcome: freeze the compatible candidate rules,
signal clock, protective activation, short-to-cash policy, quantity policy,
cost stresses, full portfolio branching, end-of-study censoring, valid minute
windows, negative controls, screening gates and cumulative trial ledger in a
new design commit. Cash bounds alone do not permit summing independently chosen
favorable trade bounds if later exposures differ.

The old minute readiness study remains `RESEARCH_READINESS_BLOCKED`; its power
and rejected-source decisions are preserved. Previously inspected history
remains spent development data even when replayed at finer resolution. A new
PnL-independent data eligibility policy does not turn it into untouched evidence.
After a historical survivor, freeze a separately powered future confirmation
protocol before its observations begin. No viable-candidate claim or automatic
orders are authorized by this engineering work.
