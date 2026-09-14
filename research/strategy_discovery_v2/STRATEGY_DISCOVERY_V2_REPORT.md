# Strategy Discovery v2: unrelated mechanism tournament

## Status

Development screening only. No untouched OOS claim. No profitable-edge claim. Live execution remains disabled.

## Protocol

The protocol was frozen in `config/strategy_discovery_v2.json` before outcomes were inspected. It excluded strategy classes already covered elsewhere in the repository (Donchian/EMA momentum, Bollinger mean-reversion and squeeze, intraday reversal, trend pullback, volatility-scaled momentum, Fibonacci/HTF, basis convergence, cross-sectional momentum, gamma exposure, and existing ENA mean-reversion).

The new tournament covered 16 unrelated families from simple local momentum/reversal and BTC lead-lag through book/microprice/aggressive-flow pressure, flow-price disagreement, absorption, sweep continuation/exhaustion, and execution-aware microstructure composites. “Institutionally inspired” means public-data microstructure proxies only; it does not imply proprietary institutional logic, hidden-liquidity detection, queue-position inference, market-impact estimation, or MBO/order-ID data.

Development observations came from 12 independent ENA causal capture batches. Each capture batch is one dependence cluster. State prediction was evaluated before strategy PnL. Robust transforms and thresholds were fitted on training clusters only. Strategy translation used non-overlapping entries and realistic 12/16/20 bps round-trip cost cases.

## State prediction

64 family × horizon trials were evaluated. 28 passed the PnL-independent state screen. Leading median leave-one-batch-out Spearman associations were:

| Family | Horizon | Median rho | Positive clusters |
|---|---:|---:|---:|
| flow-price disagreement | 300s | +0.141 | 11/12 |
| sweep exhaustion reversal | 300s | +0.136 | 10/12 |
| sweep exhaustion reversal | 60s | +0.135 | 9/12 |
| simple local reversal | 300s | +0.121 | 9/12 |
| BTC divergence convergence | 60s | +0.119 | 9/12 |
| book pressure follow | 60s | +0.102 | 10/12 |
| simple local reversal | 60s | +0.095 | 9/12 |
| flow-price disagreement | 60s | +0.084 | 10/12 |
| microprice pressure follow | 15s | +0.077 | 10/12 |

These are state/direction associations only, not trading-edge evidence.

## Strategy translation

The 28 state-screen passers produced 168 strategy translation rows across q70/q85 entry thresholds and 12/16/20 bps cost cases. Zero strategies passed the frozen 16 bps economic gate.

Best 16 bps development results by median cluster net expectancy included:

| Family | Horizon | Entry | Trades | Gross bps/trade | Net bps/trade | Positive net clusters |
|---|---:|---:|---:|---:|---:|---:|
| simple local reversal | 60s | q85 | 65 | +6.696 | -9.304 | 0/12 |
| sweep exhaustion reversal | 300s | q70 | 23 | +5.990 | -10.010 | 4/12 |
| BTC divergence convergence | 300s | q70 | 23 | +4.408 | -11.592 | 3/12 |
| pressure consensus | 300s | q70 | 24 | +3.464 | -12.536 | 2/12 |
| sweep exhaustion reversal | 60s | q85 | 71 | +3.391 | -12.609 | 0/12 |
| flow-price disagreement | 300s | q70 | 24 | +3.379 | -12.621 | 3/12 |

Even the strongest gross case, 60-second local reversal q85, had only +6.696 bps/trade median gross expectancy. It remained negative under the lowest 12 bps round-trip cost case (-5.304 bps/trade). Therefore the short-horizon lane is execution-economically blocked rather than rescued by a more favorable realistic cost scenario.

Several 300-second mechanisms had positive gross expectancy but only 23–24 total non-overlapping trades, below the predeclared minimum 40, in addition to being net-negative.

## Interpretation

The new information set contains weak-to-moderate directional structure, especially in flow-price disagreement, sweep exhaustion, local reversal, BTC/local divergence and book pressure. This is a research improvement over the retired discovery-v1 directional mechanism, but the payoff per event is too small relative to target-venue friction.

No candidate should be frozen for promotion from this screen. MAE/MFE and stop-path claims are not made from fixed-horizon market-state observations; any future candidate that advances must be replayed from raw causal data before risk-path promotion.

## Next protocol direction

Do not spend more short-horizon epochs trying to squeeze 12–20 bps of friction out of 2–7 bps gross signals. The next independent strategy-discovery lane should change economic geometry toward lower turnover and/or market-neutral payoff mechanisms on minutes-to-hours horizons, while retaining the same trial ledger, calendar dependence clusters, realistic costs, reversed controls, and future-after-freeze validation.
