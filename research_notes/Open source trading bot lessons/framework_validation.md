# Validation and backtest-realism tooling in open-source trading frameworks (as of 2026-10-09)

Method note: pages were fetched via a summarising fetch tool (small model), so wording is paraphrase; doc versions are "stable"/"latest" unless marked nightly. No user-reported failure-rate statistics were found. OctoBot, Hummingbot paper-trade internals, Jesse lookahead internals and LEAN fill/latency model pages were not reached.

## 1. How freqtrade lookahead-analysis and recursive-analysis detect bias, and reported failure rates

### Takeaway
Lookahead-analysis is a black-box differential test: it re-backtests with truncated data and checks whether signals/indicators at the same candle change. Recursive-analysis varies startup candle count and checks whether last-row indicator values drift. I found no published failure rate for community strategies.

### Cited Findings
- Lookahead-analysis does not read strategy code. Baseline backtest over all pairs records indicator values and entry/exit signals; stops if trades < `--minimum-trade-amount`. For each signal (default up to 20, `--targeted-trade-amount`) it runs a separate backtest on that signal's pair with a sliced timerange and compares the dataframe column by column against baseline; any difference flags bias. Output columns: has_bias, total_signals, biased_entry_signals, biased_exit_signals, biased_indicators. — [freqtrade lookahead-analysis](https://www.freqtrade.io/en/stable/lookahead-analysis/)
- Forced settings to avoid false positives: cache off, max-open-trades >= number of pairs, dry-run wallet ~1bn, fixed stake 10,000, protections off, market orders unless `--allow-limit-orders`. — same page
- Stated limitations: false negatives (only triggered signals checked); pairlist-dependent logic (rankings, `len(dp.current_whitelist())`) gives false positives; position stacking distorts; limit orders/custom_entry_price cause false positives; FreqAI targets falsely flagged; biased exits can be side effects of biased entries. Docs have an inconsistency between flag names `--lookahead-allow-limit-orders` and `--allow-limit-orders`. — same page
- Recursive-analysis does not backtest; it computes indicators only. Benchmark = indicators over full timerange; reruns for each `startup_candle_count` (defaults 199, 499, 999, 1999); compares the last row against benchmark and reports percent variance per indicator. Docs recommend >=5000 candles and a high-priced pair (BTC/ETH). `nan%` = insufficient data. Cache forced off. Available via freqUI and REST (`POST /api/v1/recursive_analysis`). — [freqtrade recursive-analysis](https://www.freqtrade.io/en/stable/recursive-analysis/)
- Recursive limitations: only last row compared, so variance is not tied to trade impact; only `populate_indicators` and `@informative` indicators analysed (not entry/exit trend functions); exchange candle limits can cap usable startup count (Binance example 4999). It also runs a simple lookahead check on indicator values only. — same page
- Failure rates: searches found only an awesomefreqtrade list category "Strategies with lookahead bias" with no counts. freqtrade-strategies repo README mentions no lookahead results. — [awesomefreqtrade list](https://awesome.ecosyste.ms/lists/thinkong%2Fawesomefreqtrade), [freqtrade-strategies](https://github.com/freqtrade/freqtrade-strategies)
- Strategy-callback doc rule: use `current_time` not `datetime.now()` for backtest-safe time logic. — [strategy callbacks](https://www.freqtrade.io/en/stable/strategy-callbacks/)
- Jesse claims lookahead-free multi-timeframe backtests by construction (strategy executes after candle close); this is a README claim, not verified. — [Jesse README](https://github.com/jesse-ai/jesse/blob/master/README.md)

### Inferences
- The truncation-differential idea is framework-independent and cheap to port: re-compute signals on data truncated at t and require identical output for rows <= t. Our 8h/daily pipelines could add this as a unit test for every feature function (stronger than reviewing code).
- Recursive check maps to warm-up sensitivity of EMA/rolling features: compare last value across different history lengths.
- Because both tools only test triggered signals / last rows, they miss bias that does not manifest on the sampled window (acknowledged false negatives).

### Gaps
- No quantitative community failure rate found (searches of GitHub/Reddit surfaced nothing). Would need freqtrade GitHub issues/Discord, or running the tool on the strategies repo.
- Exact slicing mechanics (how the timerange is truncated per signal) are not specified in the docs fetched; source code not read.

## 2. Hyperparameter-optimisation safeguards

### Takeaway
Freqtrade hyperopt offers drawdown/ratio-based loss functions and a trade-count penalty (MultiMetric) but no built-in walk-forward or out-of-sample split. Stronger CV tooling exists in vectorbt PRO (purged/combinatorial CV), Jesse (Monte Carlo), and LEAN (scheduled walk-forward via `train`). Passivbot's docs explicitly say its screening creates no independent holdout.

### Cited Findings
- Freqtrade loss functions: ShortTradeDur (default), OnlyProfit, Sharpe, SharpeDaily, Sortino, SortinoDaily, MaxDrawDown, MaxDrawDownRelative, MaxDrawDownPerPair (worst pair is objective), Calmar, ProfitDrawDown (tunable `DRAWDOWN_MULT`), MultiMetric (profit, drawdown, profit factor, expectancy, win rate; penalises epochs with too few trades). — [freqtrade hyperopt](https://www.freqtrade.io/en/stable/hyperopt/)
- Hyperopt doc has no OOS/walk-forward procedure; advice is to limit `--timerange` and re-backtest with identical config. Overfitting cautions: decimals capped at 3 places by default, start with narrow spaces, optimise trailing separately, run multiple `--random-state` seeds, early stop at ~20-30% of epochs, gains flatten after 500-1000 epochs; hyperopt/backtest mismatch checks (config overrides, stale JSON params, protections). — same page
- Backtesting doc statistical caveats: mean-profit p-value assumes iid trades (overlap makes it optimistic); testing many strategies yields low p-values by chance. — [freqtrade backtesting](https://www.freqtrade.io/en/stable/backtesting/)
- vectorbt PRO: walk-forward CV with purging, combinatorial CV with purging and embargoing (López de Prado inspired), `Splitter.from_purged_kfold(purge_td, embargo_td)`, `@vbt.cv_split` decorator; open-source vectorbt has RollingSplitter/ExpandingSplitter/RangeSplitter. — [vectorbt PRO optimization](https://vectorbt.pro/features/optimization), [PRO CV tutorial](https://vectorbt.pro/tutorials/cross-validation/), [vectorbt splitters](https://vectorbt.dev/api/generic/splitters)
- Jesse: Optuna + Ray optimisation with "easy cross-validation" (README claim); Monte Carlo with (a) trade-order shuffling and (b) candle-based perturbation; interpretation table compares original vs worst 5% / median / best 5%; original better than best 5% signals likely overfit. — [Jesse README](https://github.com/jesse-ai/jesse/blob/master/README.md), [Jesse Monte Carlo docs](https://docs.jesse.trade/docs/research/monte_carlo), [interpreting results](https://docs.jesse.trade/docs/monte-carlo/interpreting-results)
- LEAN walk-forward: implemented by user via scheduled `train` with trailing `history` window; docs note more frequent re-optimisation raises overfitting risk; no validation method, OOS approach, or parameter-count limit given. A native WFO API was a roadmap/forum request (scheduled "for 2023" per founder; status unconfirmed; a PR QuantConnect/Lean#9611 is mentioned by a third-party write-up). — [LEAN WFO docs](https://www.quantconnect.com/docs/v2/writing-algorithms/optimization/walk-forward-optimization), [forum thread](https://www.quantconnect.com/forum/discussion/414/walk-forward-optimization-can-we-have-this-too/)
- Passivbot optimiser: pymoo backend, NSGA-II (<=3 objectives) / NSGA-III otherwise; objectives via `optimize.scoring` (e.g. adg vs worst drawdown); constraint violations penalised; only exact Rust backtest results enter the Pareto front; GPU proxy screening has drift gates (`drift_halt` 0.6, 128-sample window) comparing proxy vs exact ranks; docs state screening "does not create an independent holdout test"; scenario suites with own date ranges/coins/exchanges. — [Passivbot optimizing.md](https://raw.githubusercontent.com/enarjord/passivbot/master/docs/optimizing.md) (only first 100k of 137k chars read)
- No framework in this set was found implementing Deflated Sharpe or PBO natively; PBO exists as an R package (CSCV). — [pbo R package](https://cran.hafro.is/web/packages/pbo/readme/README.html)

### Inferences
- Our repo (DSR/PBO, trial ledger) already exceeds what freqtrade/LEAN provide natively. Candidates worth borrowing: purge/embargo in CV (vectorbt PRO), Monte Carlo order-shuffle and candle-perturbation percentile test (Jesse), worst-pair/worst-scenario objectives (freqtrade MaxDrawDownPerPair, Passivbot scenario suites), proxy-vs-exact drift gates if any fast proxy scoring is used.
- Trade-order shuffling is a drawdown-path test only; it says nothing about edge existence.

### Gaps
- Jesse and vectorbt PRO pages were read via search snippets only; PRO is paywalled in part.
- Passivbot remaining 37k chars of optimizing.md unread.

## 3. Fills, fees, funding, latency, depth; bar-based warnings

### Takeaway
Freqtrade is bar-based with documented intra-candle assumptions and no slippage; NautilusTrader offers the richest configurable fill machinery (book-depth fills, probabilistic slippage/limit fills, queue position, liquidity consumption, latency model) and warns that bars cannot show intrabar path. Hummingbot's docs say absolute backtest P&L is unreliable and recommend 1s candles for market making.

### Cited Findings
- Freqtrade: fees applied on entry and exit (`--fee` override); stoploss exit adds extra 2x fee adjustment; no slippage; fills at requested price if within candle high/low; entries at candle open, signal exits at next open; low assumed before high; priority exit signal > stoploss > ROI > trailing; ROI exits at configured value (can exit better if low reached it); stoploss checked before ROI so backtests can show more stoploss exits than live; `--timeframe-detail` replays a smaller timeframe to simulate intracandle moves; funding fees not mentioned on this page; position stacking (`--eps`) results not reproducible live; dynamic pairlists not reproducible; exchange limits use current not historical data. — [freqtrade backtesting](https://www.freqtrade.io/en/stable/backtesting/)
- Freqtrade callbacks: backtest adjusts a position at most once per candle (live can adjust many times); rate-based exits in `custom_exit` can be inaccurate in backtest; stoploss tested vs candle low while current_profit uses candle high. — [strategy callbacks](https://www.freqtrade.io/en/stable/strategy-callbacks/)
- NautilusTrader fill models (nightly docs): Default (matching engine book), BestPrice, OneTickSlippage, Probabilistic, TwoTier, ThreeTier, LimitOrderPartial, SizeAware, CompetitionAware, VolumeSensitive, MarketHours. Parameters `prob_fill_on_limit` (default 1.0), `prob_slippage` (default 0.0), `random_seed`. Slippage only on L1 books (incl. books built from quotes/trades/bars); L2/L3 books get price impact from the recorded book, with partial fills when crossed size is insufficient. `liquidity_consumption=True` tracks consumed size per level until new data. — [Nautilus fill models](https://nautilustrader.io/docs/nightly/concepts/backtesting/fill-models/), [fill prices and matching](https://nautilustrader.io/docs/nightly/concepts/backtesting/fill-prices-and-matching/)
- Nautilus bar execution: bars lack intrabar timing so engine assumes a continuous move through trigger (stop sell at 100, bar open 102 low 98 fills at 100; gap open 90 fills at 90); docs advise quote/trade/book data for precision. Price protection on MARKET/STOP_MARKET via `price_protection_points`. — [fill prices and matching](https://nautilustrader.io/docs/nightly/concepts/backtesting/fill-prices-and-matching/)
- Nautilus trade-based execution: trade ticks can fill passive resting orders (`trade_execution=True`); `queue_position` option fills a limit only after quantity ahead has traded; limits: LIMIT orders only, per-order estimate, hidden orders/venue priority invisible. Venue config also accepts a `latency_model` (parameters not verified). Backtest accounts/margin/funding configured under "Accounts and Margin" (not read). — [trade execution](https://nautilustrader.io/docs/latest/concepts/backtesting/trade-execution/), [backtesting overview](https://nautilustrader.io/docs/latest/concepts/backtesting/)
- Hummingbot backtesting (Condor/API docs): supports Position, DCA, Grid executors; not Order (yet), Arbitrage, XEMM (need order books); 1m candles cap at one fill per minute vs 30+ live, so 1s candles recommended (Binance Spot only); queue position unknown; path dependence; "Don't trust absolute P&L numbers"; backtests are for relative comparison, not forecasts; fees/slippage not documented on that page (a dashboard page lists a trade-cost percentage input). — [Hummingbot backtesting](https://condor.hummingbot.org/bots/backtesting), [dashboard backtest](https://hummingbot.org/dashboard/backtest/)
- QuantConnect LEAN reality modelling: per-security Fill, Slippage, Fee, Brokerage, Buying power, Settlement, Short availability, margin interest and dividend models; portfolio-level margin call and risk-free-rate models; defaults assume highly liquid assets and custom models advised for large/illiquid trading; latency not mentioned on this page. — [LEAN reality modeling](https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/key-concepts)
- Passivbot backtester: replays 1m OHLCV candles; market orders fill at next candle close shifted by `backtest.market_order_slippage_pct` plus taker fee; `limit_order_fill_buffer_pct` requires price to trade through limit by a buffer (e.g. 15 bps); maker/taker fee overrides; rejects NaN gaps, tolerates small gaps via `gap_tolerance_ohlcvs_minutes`; never zeros unrealised PnL on missing prices; funding not described in the pages read. — [optimizing.md](https://raw.githubusercontent.com/enarjord/passivbot/master/docs/optimizing.md), [backtesting.md](https://raw.githubusercontent.com/enarjord/passivbot/master/docs/backtesting.md)

### Inferences
- A cheap robustness addition for bar-based work: a limit-fill buffer (Passivbot) and a fill-probability/one-tick-slippage sensitivity run (Nautilus) as scenario grid axes, reported alongside the canonical accounting.
- Freqtrade's documented stop-before-ROI ordering is a known pessimistic/optimistic asymmetry worth checking against our bar-ordering assumption.

### Gaps
- Nautilus latency model parameters, Accounts/Margin funding handling, and bar timestamp (ts_init vs ts_event) handling not retrieved.
- LEAN default fill/slippage/fee behaviour and crypto brokerage models not retrieved; Hummingbot fee/slippage in backtest engine not documented in what I read.
- Funding in freqtrade backtests: not on the backtesting page; check futures docs.
- OctoBot: not researched (tool budget).

## 4. Shadow/paper reconciliation against live data

### Takeaway
Most frameworks offer paper/dry-run modes but few document formal live-vs-backtest reconciliation; the strongest documented patterns are freqtrade's "backtest cannot replace dry-run" guidance plus mismatch checklists, and Passivbot's use of one shared Rust orchestrator for live and backtest order logic.

### Cited Findings
- Freqtrade: "backtesting can't replace dry-run"; only forward dry-run confirms; strategies robust under detail-timeframe testing more likely to hold live; dry-run runs the live callback schedule (e.g. `bot_loop_start` ~5s vs once per candle in backtest). Protections are available in backtest/hyperopt only with `--enable-protections`. — [backtesting](https://www.freqtrade.io/en/stable/backtesting/), [callbacks](https://www.freqtrade.io/en/stable/strategy-callbacks/), [plugins](https://www.freqtrade.io/en/stable/plugins/)
- Freqtrade protections: StoplossGuard, MaxDrawdown (ratios or equity mode), LowProfitPairs, CooldownPeriod; end times rounded up to next candle. — [plugins](https://www.freqtrade.io/en/stable/plugins/)
- Passivbot: shared Rust orchestrator for order planning in live and backtest "for speed and consistency". — [Passivbot README](https://github.com/enarjord/passivbot)
- Jesse live/paper trading supports paper trading and multi-account; Hummingbot paper-trade connector behaviour not found. — [Jesse README](https://github.com/jesse-ai/jesse/blob/master/README.md)
- Nautilus design (from its docs) uses the same strategy code in backtest and live; I did not retrieve a page confirming this wording, so treat as unverified.

### Inferences
- Single-code-path (same order-planning code in live and backtest) is the main structural reconciliation safeguard; for us, the paper account replay and daily forward scoring should be checked to share the exact accounting function with historical backtests.
- Per-trade diff of dry-run fills versus a backtest of the same window (not documented as a built-in anywhere I found) would be a custom addition.

### Gaps
- No built-in automated live/backtest divergence report found in any framework.
- Hummingbot paper trading and OctoBot simulator docs not retrieved.
