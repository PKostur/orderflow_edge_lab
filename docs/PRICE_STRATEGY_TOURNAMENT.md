# Strategy Tournament v1

`strategy-tournament-v1` is a deadline-oriented development screen for well-known, source-backed crypto strategy families. It exists to broaden the search without turning the repository into an uncontrolled indicator optimizer.

## What it tests

The tournament runs seven pre-specified families:

1. Donchian / trading-range breakout.
2. EMA time-series momentum normalized by ATR.
3. Bollinger-band plus RSI mean reversion.
4. Bollinger squeeze followed by breakout.
5. Standardized short-horizon reversal.
6. Trend pullback using EMA structure and RSI.
7. Volatility-scaled momentum.

These families were chosen before tournament results were inspected. They represent trend, volatility-expansion, mean-reversion and momentum hypotheses found repeatedly in the crypto/technical-trading literature. Published historical profitability is treated only as a reason to test a family, never as evidence that it will remain profitable here.

## Parallel design

Historical data is prepared once for each timeframe: `5m`, `15m` and `1h`. The workflow then launches the seven families across the three timeframes as a 21-cell matrix with up to 20 concurrent runners.

Each cell evaluates its entire frozen parameter grid at 12, 16 and 20 bps round-trip costs. Every trial is retained, including failures and losing variants. No losing cell is silently dropped from trial accounting.

## Data and causality

The development universe is fixed before strategy PnL is inspected:

- BTCUSDT
- ETHUSDT
- SOLUSDT
- XRPUSDT
- DOGEUSDT
- BNBUSDT
- ADAUSDT
- LINKUSDT
- SUIUSDT
- ENAUSDT

The historical development period is 2026-03-01 through 2026-09-11 inclusive. Signals are computed only from information available at a completed candle and become executable at the next candle open. The tournament therefore does not fill a signal on the same close used to create it.

The historical breadth source is Binance USD-M public futures data. The target project remains MEXC Futures. A Binance result is therefore development/transfer evidence only and cannot be described as MEXC untouched out-of-sample evidence. A selected candidate must be frozen and tested unchanged on later MEXC paper/shadow data.

## Economics

The tournament uses 12, 16 and 20 bps round-trip cost cases. The first two reflect the approximate round-trip API fee floors implied by MEXC's June 2026 API Futures fee schedule—before spread, adverse selection or additional slippage. The 20 bps case adds a modest friction stress.

This deliberately sets a much harder executable hurdle than the older 4/8 bps discovery diagnostics. A candidate that only works before realistic costs is not useful for the deadline release.

## Dependence and screening

The independent screening unit is a **calendar 21-day time fold**. Symbols inside the same period are aggregated into that fold rather than counted as independent replications. This prevents ten highly correlated crypto markets during one event from masquerading as ten independent confirmations.

A variant is only `screening_eligible` when all of these are true after the stated cost case:

- at least 80 trades across contributing folds;
- at least 6 independent calendar folds;
- median fold expectancy is positive;
- median fold profit factor is greater than 1;
- at least 60% of independent folds have positive median expectancy.

Passing that screen is not candidate promotion. The adversarial lead must still inspect parameter-neighborhood stability, symbol concentration, trial count and economic plausibility. An isolated optimum surrounded by losing neighboring parameters is not a preferred candidate.

## Forward rule

Only a development candidate that survives the screening and adversarial review may be frozen. After freeze:

1. Exact rules and economics are hashed/frozen.
2. Forward evidence begins on later MEXC public market data / paper-shadow operation.
3. No thresholds or parameters are changed after the forward period begins.
4. Forward results feed the existing trial ledger, holdout audit, execution-safety and promotion gates.

The September 16 deadline does not change those evidentiary labels. The deliverable can be a complete research/paper program even if no strategy earns the right to be called a verified profitable edge.

## Source basis

The research basis includes published work on Bitcoin trading-range breakouts, large-scale simple technical-rule testing with realistic transaction costs and out-of-sample portfolios, intraday crypto momentum/reversal, price-trend forecasting across broad cryptocurrency universes, and risk-managed cryptocurrency momentum. These papers motivate families; they do not certify this implementation or future returns.
