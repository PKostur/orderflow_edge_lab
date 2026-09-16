# Discovery Process v2

Status: research architecture only. Existing frozen candidates remain untouched.

## Objective

Replace the previous single-pipeline strategy-discovery process with a falsification-first, multi-engine research system. The goal is not to maximize historical PnL. The goal is to identify strategies whose behavior survives changes in data source, backtest engine, market regime, cost model, benchmark, and evaluation method.

## Core change

A strategy no longer passes because one backtest looks good. It progresses only when independent implementations agree on economically meaningful behavior.

### Engine roles

1. **Fast discovery engine — existing orderflow_edge_lab/vectorized research code**
   - Purpose: cheap hypothesis screening and feature research.
   - Not acceptable as final evidence.
   - Can run large hypothesis families, provided every trial is logged.

2. **Bias-audit engine — Freqtrade**
   - Purpose: crypto candle-strategy replication plus lookahead-analysis and recursive-analysis.
   - Mandatory for candle/indicator strategies that can be represented in Freqtrade.
   - Backtest/dry-run disagreement is a failure signal, not something to tune around.

3. **Independent event-driven replication — NautilusTrader**
   - Purpose: primary second implementation for crypto and multi-venue strategies.
   - Event-driven fills, order state, portfolio/risk state and live-like timing semantics.
   - No code imported from the discovery implementation other than an immutable strategy specification.

4. **Execution-specialist engine — Hummingbot / Quants Lab**
   - Purpose: market making, cross-exchange arbitrage, funding/basis, liquidity provision and order-book strategies.
   - Used only when the strategy depends materially on venue microstructure or order placement.

5. **Cross-asset independent engine — LEAN**
   - Purpose: gold, futures, equities, FX and cross-asset replication when appropriate.
   - Provides a separate event-driven implementation and separate ecosystem/data assumptions.

A strategy requiring unavailable exchange support must use an adapter or an alternate venue for research. Venue substitution must be versioned and can never be presented as validation on the original venue.

## Data architecture

Each experiment receives a `dataset_manifest.json` containing:
- source and retrieval timestamp;
- venue, market type and symbols;
- raw-file hashes;
- exact start/end timestamps;
- timezone and candle boundary;
- corporate-action/contract-roll handling where applicable;
- missing-data policy;
- funding/fees metadata provenance;
- whether the data were visible during hypothesis formation.

Raw datasets are immutable. Cleaning produces a new derived dataset with its own hash. No silent corrections.

### Data independence levels

- **D0:** same source, same period.
- **D1:** same source, later period.
- **D2:** independent source, overlapping period.
- **D3:** independent source, later period.
- **D4:** prospective data captured after freeze.

Claims must name the highest independence level actually achieved.

## Discovery workflow

### Phase A — hypothesis generation

Anything is allowed: papers, GitHub bots, TradingView ideas, discretionary observations, ML search, evolutionary search, market microstructure theory, copied public strategies.

Every candidate must be converted into a short immutable strategy specification containing:
- economic mechanism;
- inputs known at decision time;
- exact signal and position rules;
- holding/exit rules;
- assumed execution style;
- parameter ranges, if any;
- benchmark that could explain the return;
- expected failure regimes.

### Phase B — cheap falsification

Use the fast engine only. The question is not “how profitable is it?” but:
- does the gross signal exist before costs?
- is it concentrated in one symbol/month/regime?
- does the reversed/null version behave similarly?
- does a one-bar delay destroy it?
- is it sensitive to tiny parameter changes?
- does it outperform the simplest relevant benchmark?

Strategies that fail here are archived. No rescue optimization.

### Phase C — model-selection accounting

All tried variants enter a permanent trial ledger. Evaluation must account for the number of trials.

Required where sample size permits:
- Deflated Sharpe Ratio (DSR);
- Probability of Backtest Overfitting (PBO) using combinatorially symmetric cross-validation (CSCV);
- stationary/block bootstrap confidence intervals;
- benchmark-relative bootstrap / Reality-Check-style test for families with many variants.

No candidate may hide unsuccessful siblings.

### Phase D — engine replication

The candidate specification is frozen before a second implementation is written.

The second implementation may not import signal code from the first engine. It may only consume the strategy specification and immutable data contract.

Required comparison:
- signal timestamps;
- target positions;
- executed positions;
- trade count;
- turnover;
- gross return;
- explicit fees;
- funding/borrow;
- modeled slippage;
- net return;
- drawdown.

Material disagreement between engines blocks promotion until explained prospectively.

### Phase E — adversarial execution test

The strategy must survive a cost/execution surface, not one fee assumption.

At minimum test:
- maker/taker alternatives when relevant;
- 1x, 1.5x, 2x baseline slippage;
- delayed execution by 1 bar/event;
- partial-fill or missed-fill stress for limit strategies;
- spread widening in high-volatility periods;
- funding/borrow variation;
- minimum-order and precision constraints.

Break-even cost/slippage must be reported. A strategy whose break-even friction is too close to normal venue friction is rejected even if baseline PnL is positive.

### Phase F — regime and concentration decomposition

Every result is decomposed by:
- symbol;
- year/quarter/month;
- trend/range regime;
- realized volatility bucket;
- liquidity/spread bucket;
- BTC/market beta regime for crypto;
- funding regime for perpetuals;
- long vs short side;
- top 5 trades / periods contribution.

Report the fraction of total PnL contributed by the best symbol, best month and best five trades.

### Phase G — later and independent validation

Development selects the rule. Validation cannot change it.

Validation order:
1. later-period same-source;
2. independent-source replication when possible;
3. prospective shadow.

A failed locked validation closes that exact candidate. Diagnostics may inspire a new candidate ID, never modify the failed one.

## Evaluation model

There is no single “promotion score.” A candidate receives a vector of evidence dimensions so a high return cannot compensate for invalid research.

### Validity
- no lookahead leakage;
- no timestamp ambiguity;
- no hidden survivorship/universe leakage;
- no future funding/borrow information;
- no unlogged trials;
- independent-engine agreement.

Any validity failure = automatic block.

### Economics
Report:
- gross expectancy;
- net expectancy;
- CAGR / total return where meaningful;
- Sharpe and Sortino;
- maximum drawdown and time under water;
- profit factor;
- turnover;
- fee, slippage and funding drag separately;
- break-even friction;
- return on gross exposure;
- benchmark-relative return and beta/market exposure.

No metric is sufficient alone.

### Statistical robustness
Report:
- bootstrap CI for mean/median return;
- DSR;
- PBO/CSCV when multiple variants were searched;
- positive-period fraction;
- positive-symbol fraction;
- parameter-neighborhood stability;
- engine-to-engine result dispersion.

### Concentration
Report:
- top-symbol PnL share;
- top-period PnL share;
- top-five-trade PnL share;
- Herfindahl-style contribution concentration;
- performance excluding the best symbol and best period.

### Execution robustness
Report:
- baseline modeled costs;
- 1.5x and 2x cost cases;
- 1-event delay case;
- missed/partial-fill stress where relevant;
- capacity/liquidity estimate;
- liquidation and margin feasibility if leverage exists.

## Decision states

Candidates do not receive arbitrary numerical grades. They move through explicit states:

- `IDEA`
- `DISCOVERY_ONLY`
- `FALSIFIED`
- `REPLICATION_PENDING`
- `ENGINE_REPLICATED`
- `LOCKED_VALIDATION`
- `VALIDATION_FAILED`
- `PROSPECTIVE_SHADOW`
- `EVIDENCE_ACCUMULATING`
- `LIVE_REVIEW_ELIGIBLE`

`LIVE_REVIEW_ELIGIBLE` does not mean profitable edge is proven and does not automatically enable live trading.

## Minimum promotion requirements

From discovery to independent replication:
- positive gross expectancy;
- positive net expectancy under baseline costs;
- positive benchmark-relative result;
- no single symbol >50% of aggregate PnL unless the strategy is explicitly single-symbol;
- no unexplained validity failure;
- reversed/null control materially weaker;
- sufficient event count for the strategy horizon.

From independent replication to locked validation:
- second engine agrees on direction and approximate economics;
- positive net result under at least baseline and 1.5x friction;
- parameter neighborhood is not a single isolated peak;
- DSR/PBO/Reality-Check evidence does not indicate obvious selection-driven result where applicable.

From locked validation to prospective shadow:
- exact frozen rule remains positive net of costs;
- benchmark-relative result remains positive;
- drawdown within preregistered tolerance;
- no execution/accounting discrepancy.

From shadow to live review:
- multiple completed independent periods/trades;
- observed execution assumptions close to simulated assumptions;
- no dependence on a single regime;
- live deployment plan includes hard risk limits and kill switch.

## What is explicitly removed from the old process

- ranking candidates primarily by backtest PnL;
- treating PF > 1 as meaningful by itself;
- retuning after a failed locked period;
- treating same-period cross-symbol replication as independent OOS;
- relying on one backtesting engine;
- allowing one cost estimate to decide viability;
- hiding the number of strategy variants tried;
- promoting a strategy because leverage improves returns;
- calling paper PnL proof of persistent edge.

## Research philosophy

The discovery engine should be permissive and fast. The validation system should be hostile.

The goal is to make false strategies fail cheaply and early, while making a surviving strategy earn credibility through independent implementations, independent data and prospective evidence.