# Discovery v2 calibration status

Status: **engineering calibration passed; no trading edge claim**

This file records the first calibration of the redesigned discovery process. The calibration target was the already-frozen candidate `mexc_8h_ema24_96_atr025_v1` because its EMA/ATR rule is simple enough that independent engines should agree exactly before they are trusted on harder strategies.

## 1. Signal semantics calibration — PASS

Frozen protocol: `config/discovery_v2_engine_calibration_v1.json`

Data:
- Venue: MEXC Futures public klines
- Symbols: BTC_USDT, ETH_USDT, SOL_USDT, XRP_USDT, DOGE_USDT, BNB_USDT, ADA_USDT, LINK_USDT, SUI_USDT, ENA_USDT
- Interval: 8h
- Window: 2026-07-01T00:00:00Z through 2026-09-12T00:00:00Z exclusive
- Bars per symbol: 219

Engines checked:
- existing `orderflow_edge_lab` reference implementation;
- independently written NumPy/Pandas implementation using recursive EMA and rolling true range without calling the production signal generator;
- Freqtrade 2026.8 using a genuine `IStrategy` implementation in the official stable container;
- NautilusTrader 2.0.0rc5 using its own EMA and SMA indicator classes sequentially.

Result across every symbol and external engine:
- timestamp disagreement count: 0;
- raw target disagreement count: 0;
- next-bar execution target disagreement count: 0;
- transition timestamp disagreements: 0.

Successful workflow run: `35090449339`

Preserved artifact:
- name: `discovery-v2-engine-calibration-v1`
- artifact id: `10443579622`
- SHA-256: `822c5d3f7108387a2d988347f824cf64e8dc4f2e59c5bcc5cf6670e03fcfcf20`

This proves signal-semantics parity for this calibration rule. It does **not** prove strategy profitability, market realism, or persistent edge.

## 2. Independent event-driven execution calibration — PASS

Frozen protocol: `config/discovery_v2_execution_calibration_v1.json`

Engine: NautilusTrader `BacktestEngine` 2.0.0rc5.

Purpose: verify that the frozen completed-bar signal can be reproduced as a causal next-8h-open execution sequence in a true event-driven engine rather than by shifting a vectorized return series after the fact.

Calibration fixture:
- completed bars are timestamped at the 8h close;
- strategy orders receive 1 ns simulated command latency;
- a zero-spread quote containing the next 8h open arrives 1 ns after the completed close and releases the delayed market order;
- no fees, spread or slippage are included in this calibration fixture because the objective is exact timing/accounting parity, not market realism;
- realistic execution friction remains a mandatory later evaluation dimension.

Exact result:

| Symbol | Expected fills | Actual fills | Final target | Gross realized PnL parity |
|---|---:|---:|---:|---|
| BTC_USDT | 5 | 5 | +1 | exact |
| ETH_USDT | 1 | 1 | +1 | exact |
| SOL_USDT | 3 | 3 | +1 | exact |
| XRP_USDT | 3 | 3 | +1 | exact |
| DOGE_USDT | 3 | 3 | +1 | exact |
| BNB_USDT | 1 | 1 | +1 | exact |
| ADA_USDT | 1 | 1 | +1 | exact |
| LINK_USDT | 1 | 1 | +1 | exact |
| SUI_USDT | 3 | 3 | +1 | exact |
| ENA_USDT | 3 | 3 | +1 | exact |

Total: **24 expected fills = 24 actual fills**.

For every fill, the following matched the independently derived expectation:
- side;
- quantity;
- exact next-open price within the frozen tolerance;
- timestamp within the frozen zero-nanosecond tolerance.

Final net target matched on every symbol. Gross realized PnL from the fill ledger matched the independently calculated realized PnL on every symbol.

Successful workflow run: `35090922325`

Preserved artifact:
- name: `discovery-v2-execution-calibration-v1`
- artifact id: `10444201433`
- SHA-256: `46a577e45a42eb1a7fbc12dd904e1f2a8dc420c6f0023374d4e4b7eae0edda6a`

This establishes event-driven timing and accounting equivalence for the calibration fixture. It is **not** an execution-cost model and **not** edge evidence.

## 3. Evaluation framework — IMPLEMENTED AND CI GREEN

Frozen methodology: `config/discovery_v2_evaluation_v1.json`.

Implemented in `src/orderflow_edge_lab/discovery_v2_evaluation.py`:
- moving-block bootstrap confidence interval for economic observations;
- Deflated-Sharpe-style trial-selection adjustment;
- CSCV / Probability of Backtest Overfitting diagnostics;
- centered moving-block White-style family reality check;
- 1.0x / 1.5x / 2.0x cost surface;
- break-even round-trip friction and break-even/base-cost ratio;
- best-symbol, best-month and top-five-winner concentration;
- leave-one-symbol-out expectancy;
- side decomposition;
- explicit D0-D4 evidence-independence level;
- evidence vector instead of a single promotion score.

The evaluator is deliberately unable to auto-promote a strategy. A good result in one dimension cannot compensate for a failed mandatory dimension.

Full repository CI for commit `7dd560879bcec39c88441584fbfa7a030e86e4f9` passed on:
- Ubuntu / Python 3.10;
- Ubuntu / Python 3.11;
- Ubuntu / Python 3.12;
- Windows / Python 3.12.

Workflow run: `35091152915`.

## Process consequence

Effective for Discovery v2 research:

1. `orderflow_edge_lab` vectorized simulations are **discovery-only**.
2. A candidate may not enter locked validation until its signal semantics have been independently reproduced and its execution-sensitive logic has been replicated in the appropriate independent engine.
3. Strategies whose claimed edge depends on fills, order-book mechanics, maker/taker behavior or cross-venue timing require an execution-capable engine such as NautilusTrader or Hummingbot rather than vectorized return shifting.
4. Family-level trial mining is evaluated explicitly; failed variants remain in the trial denominator.
5. Locked-validation failure closes that candidate ID. A changed strategy becomes a new candidate with a new clock.
6. Prospective D4 evidence remains mandatory for any live-review state.

## Claims boundary

- calibration complete: **yes**
- engineering parity established for the simple 8h EMA/ATR fixture: **yes**
- persistent profitable edge established: **no**
- any existing frozen candidate promoted by this calibration: **no**
- live execution enabled: **no**
