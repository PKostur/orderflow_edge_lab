# Fresh public bot batch 2: pre-outcome design

Three newly inspected implementations, absent the prior25 catalog, are frozen in `config/public_bot_batch2_v1.json`. Upstream is pinned at `f3340ce11f5bdf62f598522e64d1f5638eaa13f5`, files under `user_data/strategies/berlinguyinca/`: ASDTSRockwellTrading.py, AwesomeMacd.py, CofiBitStrategy.py. These files contain no Bollinger calculations. Mathematical rules are independently implemented; no upstream code copied. Root license is GPL3. Public code is source evidence, not profitability evidence.

This is a declared **8h adaptation**, not an unchanged Freqtrade bot reproduction. Native5m/1h timeframes, ROI tables and stops differ as explicitly recorded. Frozen MACD12/26/9, AO5/34, stochastic5/3, EMA5 and ADX14 numeric rules are retained. Both MACD candidates are related; their signal overlap must be disclosed. No indicator is added to an existing frozen lane.

All rules, costs, administrative timeout, controls and gates are committed before computing any new candidate outcomes. Prior ETH/SOL/LINK/BTC history is already spent development data, irrespective of the new strategy identities. Never describe these runs as unseen validation. Full trial history remains relevant; the three-candidate interval is descriptive rather than a calibrated discovery test across the entire prior search.

## Execution and diagnostics

Closed-candle decisions; market entry/exit at next open; one fully funded long per symbol; no overlapping position, no same-decision exit/re-entry; fixed30bar timeout. Pending positions are reported and marked, not silently discarded. Fee10bps each side plus20bps assumed combined spread/slippage gives40bps reference;20/40/60/80bps stress. These assumptions are not historical execution calibration.

Retain every signal, skipped entry, event, pending position, source/config hash, return, BTC matched return, MFE/MAE and ambiguity caveat. Equal starting symbol sleeves compound internally with symmetric half-cost entry/exit and mark open prices including pending positions. Report net/gross/PF, years/symbols/months, UTC clocks and overlapping fixed session windows, BTC regimes, dependence by entry ISO week, leave-one-week/symbol, four-week block bootstrap, beta sensitivity, +7bar timing and500 same-entry-week timing controls preserving each observed holding length. Controls may overlap; not a causal counterfactual or formal p-value.

Screen gates:100completed events,52entry weeks, mean net40>5bps, net80>0, every symbol net40>0, at least2/3 years positive, worst leave-week net40>0, drawdown magnitude<30%, positive descriptive family-adjusted bootstrap lower bound for net40 AND BTC excess, timing-placebo tail<=.05. Every gate must pass; all3 results disclosed; no retuning. Bootstrap2000 replicates, contiguous blocks of4 calendar weeks including empty weeks; alpha.05/3 descriptive two-sided width. Trade weighted ratio estimator.

Historical screen survival only authorizes designing later confirmation. A viable candidate requires adequate independent information, a genuinely untouched post-freeze period, execution calibration, independent semantics parity, and approval-bound shadow reliability. No live order capability is added. A failed batch remains rejected. Continuing to search cannot guarantee a viable strategy, and each later batch needs a separate frozen design before seeing its outcomes.

TDSequential excluded for complicated count carry behavior; CCIStrategy excluded for Bollinger calculations and interpolated higher-timeframe data; MultiRSI excluded for resampling complexity; UniversalMACD excluded for optimized ranges. These are source exclusions, not failed backtests. There are three trading cells in this batch, no parameter search. Existing cumulative ledger is preserved.
