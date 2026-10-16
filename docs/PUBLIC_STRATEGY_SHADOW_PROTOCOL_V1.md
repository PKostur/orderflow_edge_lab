# Public-strategy transfer and prospective-shadow research v1

**Status: DRAFT / DEVELOPMENT ONLY.** The executable module, 25-source inspection catalog and three candidate definitions are engineering research scaffolding. There is no claim of an independent strategy edge. The source survey is [here](PUBLIC_STRATEGY_SOURCE_SURVEY_2026_10_10.md). This lane does **not** change any DV2, DON8, Universal, D4, portfolio, paper-account, approval or promotion definition.

## Seven distinct hypotheses ranked for research feasibility

Rank is an **engineering priority**, not predicted profitability. No rank was selected by looking at future PnL.

| Rank | Hypothesis | Mechanism / distinguishing test | Data and cost obstacle | Current disposition |
|---|---|---|---|---|
| 1 | Relative-volume impulse continuation | A high-volume bullish close near the bar high precedes continuation beyond BTC's same-window move | Closed OHLCV, next-open slippage, 20 bps spot round trip | **Implemented** as PSV1-VOLUME-IMPULSE; 24-bar baseline, 2x volume, 80 bps range, close location >=0.80, hold 3 bars |
| 2 | Failed downside-break recovery | Price sweeps a 30-bar low but closes back inside and high in its own range | Close-only signal avoids pretending to fill the wick; gaps remain material | **Implemented** as PSV1-FAILED-DOWNSIDE; close location >=0.70, hold 2 bars |
| 3 | Rolling volume-weighted price displacement | Bullish recovery bar remains >=70 bps below a 24-bar volume-weighted typical-price reference | Volume source quality, overnight jumps and BTC beta | **Implemented** as PSV1-VWAP-REVERSION; hold 2 bars |
| 4 | Depth-imbalance state prediction | Synchronized L2 bid/ask imbalance forecasts short-horizon future midprice state before any trading test | Version-complete order book, crossed/stale snapshots, queue fills | Design hypothesis only; existing order-flow infrastructure should be reused, not retuned |
| 5 | Prior-session range breakout | Previous session's realized range sets next-session opening breakout thresholds | Venue session clocks, DST, tick path, stop/limit fills | Design hypothesis only; requires independent event-driven parity |
| 6 | Spot/perpetual basis convergence | Basis/funding dislocation mean reverts after two-leg fees and carry | Two-leg atomicity, venue transfer, margin, funding and borrow | Design hypothesis only; **no leverage or two-leg execution enabled** |
| 7 | Inventory-aware liquidity provision | Quote skew and cancel discipline improve maker economics net of adverse selection | Queue priority, cancel delay, inventory risk, rebates | Design hypothesis only; requires L2/tick execution simulation |

These seven are a **single inspected trial family**, not seven independent positive discoveries. The first three were chosen because they can be falsified on identical, contiguous, locally supplied spot OHLCV and require no live venue connectivity. Their entry mechanisms are momentum continuation, failed-break reversal and volume-weighted mean reversion, respectively.

## Shared preregisterable design for the three implemented experiments

Canonical draft: `config/public_strategy_shadow_v1.json`. Code: `src/orderflow_edge_lab/public_strategy_shadow.py`. CLI: `orderflow-public-strategy-shadow`. Tests: `tests/test_public_strategy_shadow.py`.

| Item | Frozen candidate definition in draft |
|---|---|
| Trial family | `public-strategy-shadow-v1`; three comparisons, all reported, no best-of selection |
| Symbols | ETH_USDT, SOL_USDT, LINK_USDT, with BTC_USDT as the same-time market comparator |
| Venue / instrument | **Operator-supplied spot OHLCV only**; no implied validity of Futures candles as spot |
| Candle clock | UTC 8h bar **open** timestamp; strictly contiguous, aligned, positive OHLC, nonnegative volume |
| Signal availability | Compute only after the entire bar closes; no current unfinished bar or future bar in features |
| Hypothetical entry | Open of the **next** 8h bar; no close-of-signal-bar fills |
| Exit | Open after 2 or 3 held bars (per experiment), no intrabar stop/target claims |
| Direction | Long only, one nonoverlapping position per symbol per experiment |
| Fees / friction | 6 bps per side + 4 bps round-trip spread + 4 bps round-trip slippage = **20 bps round trip** |
| Stress | Double the entire 20 bps cost to 40 bps; no parameter retuning |
| Comparator | Matched BTC spot long over exactly the same entry/exit timestamps and assumed cost |
| Primary endpoint | Per-trade **net excess versus BTC** in bps, reported alongside standalone net and double-cost net |
| Dependence unit | UTC ISO calendar week **across all symbols**, not each trade or each coin as independent |
| Minimum review sample | 60 completed trades, 12 calendar-week clusters, 3 distinct symbols **per experiment** |
| Proposed economic hurdle | Mean excess >5 bps/trade; standalone mean net >0; double-cost mean net >0 |
| Uncertainty | Week-cluster descriptive interval; independent calibrated inference with family-wise error control across all three experiments is required before any formal pass |
| Primary falsifiers | Failure to beat BTC by the predeclared hurdle; failure after friction stress; nonpositive or unstable cluster-level excess; lack of independent clusters |
| Non-decision states | Insufficient sample, unverified source/freeze, inadequate power, unmatched external engine, ambiguous executable fills, incomplete coverage |
| Negative controls | Same-window BTC return and doubled-cost stress; later independent replication should add time-shift and sign-reversal controls with new preregistration |
| No-go boundary | No promotion, paper orders, live orders, leverage, strategy parameter edits to old frozen lanes or profitable-edge language |

**Critical distinction:** 12 weeks and 60 trades are minimum evidence-volume gates, **not** a validated power calculation. The module's week-cluster interval uses a simple normal approximation with a three-comparison z multiplier (2.394) and is **descriptive only**, particularly unreliable with few dependent weeks. The module intentionally never issues a statistical pass/fail verdict. An independent reviewer must predefine and verify the actual multiplicity-adjusted test, source independence, and effect-size/power assessment before opening a formal confirmation window.

### Running the implementation

Supply four **local** CSVs named `BTC_USDT.csv`, `ETH_USDT.csv`, `SOL_USDT.csv`, `LINK_USDT.csv` in one directory. Each file needs columns `timestamp,open,high,low,close,volume`; timestamps are UTC **bar opens** (`Z`), strictly 8 hours apart, with an identical time grid across all four symbols. The `--as-of` value is the operator-audited time through which the last supplied bar is **fully closed**. No network is accessed.

```bash
python -m pip install -e .
orderflow-public-strategy-shadow \
  --config config/public_strategy_shadow_v1.json \
  --data-dir /path/to/audited_spot_csv \
  --as-of 2026-10-01T00:00:00Z \
  --mode development \
  --output artifacts/public_shadow_development_001.json
```

The output file is **exclusive-create** and cannot overwrite prior results. It contains the canonical spec hash, SHA-256 of each exact raw CSV, every eligible signal, pending and completed outcomes, BTC controls, friction stress, week clusters, sample gates, and explicit `verified_out_of_sample_evidence: false` / `deployment_eligible: false`. No signal or order is transmitted. The data-dir is an example; no data are supplied or downloaded by this change.

`--mode prospective` is deliberately **blocked** by the draft config. To open a future watch:

1. Finalize source provenance, realistic venue-specific spot fees/spread/slippage, sample-power plan, matched-control adequacy, and independent engine calibration **without looking at the future evaluation window**. Changes after development inspection require a **new versioned candidate**.
2. Create a separate versioned, immutable config that declares `FROZEN_BEFORE_PROSPECTIVE_START`, `frozen_at_utc`, a verifiable pre-start `freeze_commit` pointing to the committed specification, and a `prospective_start_utc` **strictly later** than the freeze. Independently audit the Git history. The CLI checks field consistency, but **cannot authenticate a caller-declared Git timestamp or commit**.
3. Register the new watch in the preregistration/inspection/trial registries under its new identifier, and retain raw source snapshots/hashes before scoring. Preserve all signals including pending, missing and negative outcomes; do not choose symbols, dates or variants by their results.
4. Capture new contiguous spot data **after** the frozen boundary. The prospective runner refuses future as-of timestamps, stale data, gaps, duplicate bars, unclosed candles, non-UTC timestamps and mismatched grids. Use a separate immutable output per coverage update.
5. At the scheduled formal review, apply the *independently validated* clustered, multiplicity-controlled protocol; report all three experiments, missing observations and failed hypotheses. Run Freqtrade lookahead/recursive checks and NautilusTrader independent next-open fill parity where the data/engines permit. None of those external engine replications is claimed complete by this PR.

### What is implemented and what is not

Implemented: source survey, ranked transfer hypotheses, three deterministic signal algorithms, fully specified draft cost/entry/exit/control rules, strict CSV ingestion, no-overlap and pending-event handling, offline CLI, hash-provenance report, sample/cluster diagnostics, and synthetic regression tests.

Not implemented or authorized: an authenticated data collector, broker or exchange connection, an automatic scheduled prospective watch, formal power or calibrated significance testing, independent third-party engine replications for these three candidates, independent raw-data authenticity, an OOS freeze certification, or live/paper orders. These are deliberate gates, not results to be inferred from green CI.

**Research integrity:** This work must not be used to alter the frozen DON8, DV2, D4, Universal or other existing prospective lanes. Earlier failed research stays failed; an idea in an external code example does not rescue it.
