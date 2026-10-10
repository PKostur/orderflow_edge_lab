# Failed-downside independent replay and replication feasibility

**Disposition: a prospective candidate freeze is not justified.** The independent replay matches all 255 signals, 2 skipped overlaps and 253 completed events from the unchanged v1 definition. The design audit exposes insufficient precision for the +5 bps BTC-relative hurdle and incomplete venue/execution calibration. This study closes the feasibility step without inventing a future T0 or opening a watch. Failed downside remains development-interesting, not established.

Study ID: `PSR1-FAILED-DOWNSIDE-FEASIBILITY`. Parent: `PSV1-FAILED-DOWNSIDE`. Design: `config/public_failed_downside_replication_design_v1.json`. Accounting: `config/public_strategy_research_ledger_v1.json`. No existing global frozen registry entry or prospective protocol was edited.

## Independent engineering replay

`src/orderflow_edge_lab/failed_downside_replication.py` independently computes the signal with a streaming deque of exactly 30 prior lows and an opening-event execution schedule. It does not call the v1 signal detector, evaluator, development variant function, or summary routine. It shares only the strict CSV/UTC data validator. A signal requires current low < prior minimum < current close and current close location >=0.70; it does **not** require a bullish candle. Entry is the next opening, exit two held bars later, and a new entry at the same open as an exit is allowed. No intrabar stop logic is added.

The exact reference ledger matches every field and all computed returns to 1e-9 bps against the committed Binance report. Source hashes must match before comparison. This is independent internal strategy/execution logic on **spent Binance data**, not external engine validation or new market evidence. Tests explicitly cover bearish recovery bars, strict prior-low breaches, causal prefix signals, same-opening exit/reentry, final pending events, and the inability of duplicated same-week trades to manufacture independent information.

This audit also found that Git had normalized the aligned CSV line endings in the prior commit, while the recorded source hashes referred to the collector's original CRLF bytes. A scoped `.gitattributes` rule and restored original CSV bytes make the committed objects and Linux/Windows checkouts match the existing manifest. No candle value or historical result changed. A test checks all four raw source and aligned CSV hashes against both provenance records.

## Sample and power feasibility

The primary endpoint remains per-trade altcoin excess over the identical BTC holding window, with the original +5 bps economic hurdle. The observed mean is +34.0347 bps from 253 trades across 120 active UTC ISO exit weeks in a 320.286-calendar-week grid. The weekly cluster ratio-of-sums standard error is **31.1993 bps**. The calculation is:

`SE = sqrt(G/(G-1) * sum_week(sum_trade(excess - pooled_mean)^2)) / total_trades`.

The design uses one-sided alpha `0.05/9 = 0.00555556` and 80% target power. Nine is the disclosed minimum number of distinct inspected threshold cells; 25 sources and seven hypothesis families were also inspected. This does not claim to calibrate the full selection process. The scenarios use the optimistic normal approximation `G_required = G_observed * ((z_(1-alpha) + z_0.8) * SE / (true_mean - 5))^2`. The mean under the alternative is separate from the hurdle: proving a true mean of +10 above a +5 hurdle means detecting a 5 bps difference.

| Assumed true mean excess | Difference above hurdle | Required active weeks, optimistic | Calendar years at historical event rate |
|---|---:|---:|---:|
| +10 bps | 5 bps | 53,404 | 2,732 |
| +25 bps | 20 bps | 3,338 | 171 |
| +50 bps | 45 bps | 660 | 33.8 |
| +100 bps | 95 bps | 148 | 7.6 |

At the observed rate, one year produces about 41 trades and 20 active weeks; two years about 82 trades and 39 active weeks; five years about 206 trades and 98 active weeks. Their optimistic 80%-power detectable true means are +266, +190 and +122 bps respectively. The historical +34 bps effect is far below these fixed-horizon detectable effects. Sixty trades and twelve weeks therefore cannot be represented as an adequately powered confirmation design.

These figures are **feasibility estimates**, not validated power guarantees or literal forecasts spanning centuries. They assume stationary variance, event rate and independent future weeks; clustered extremes, market change and serial dependence can worsen precision. Aggregating several venues from the same market period does not multiply independent calendar-week information. The tests enforce the cluster calculation's invariance to duplicating trades inside their original weeks.

## Venue and execution gates

The OKX public history access probe returned HTTP 403 and obtained no candles. The committed `source_probe.json` records the attempted URL and error; the error body was not retained. The requested native interval was not validated by the failed probe. An eventual source protocol must use a documented interval, with complete 1h candles aggregated to eight fixed UTC hours where needed, exact market/symbol mappings, complete listing coverage and no gap filling. A different venue's same-period history would be venue robustness evidence, not untouched future OOS.

OKX's [official API guide](https://www.okx.com/docs-v5/en/) documents the public historical candle interface; its [regional spot fee guidance](https://www.okx.com/en-eu/help/what-are-the-new-trading-fees-for-eea-users) makes fee tier/account configuration relevant. No single generic fee example is substituted for the user's applicable rate. Historical executable spread, depth, impact and latency are unavailable from OHLCV alone. A later execution study must fix order notional, obtain timestamped bid/ask and depth around intended boundaries, model both fills, verify the applicable taker fee, and apply the identical model to BTC. Current next-open prices remain hypothetical.

No authenticated account endpoint, credentials, paper mutation or order endpoint was used. There is no claim of calibrated executable fills, Freqtrade or NautilusTrader parity, independent historical replication, or prospective evidence.

## Concrete next gate

Do not schedule a prospective watch for this candidate on the present evidence. A successful source-entitlement audit could support a separately committed **descriptive venue replication** design, with its market, coverage, costs and full trial accounting fixed before successful price retrieval. Formal future confirmation also requires an economically plausible effect and a sample design that can reach adequate precision in a realistic horizon. If these gates cannot be met, close the lane without retuning and pursue a new hypothesis under a new identifier.

Reproduce the completed engineering and feasibility audit with a new output directory:

```text
python -m orderflow_edge_lab.failed_downside_replication --exact-report artifacts/public_spot_8h_20261010/exact_v1_report.json --data-dir artifacts/public_spot_8h_20261010/aligned_csv --design config/public_failed_downside_replication_design_v1.json --output-dir artifacts/public_failed_downside_feasibility_20261010
```
