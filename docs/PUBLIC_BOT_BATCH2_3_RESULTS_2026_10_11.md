# Fresh public bot research: batches 2, 3 and 4

Six new source-derived eight-hour adaptations were tested without parameter optimization. **All six are rejected as adapted; no viable candidate has been established.** This does not reject the native upstream bots, whose original timeframes, stop/ROI and engine semantics were not reproduced.

## Pre-outcome registration and data

Batch 2 design commit `063e170590f117e1e771b8ecb9581aef3e69737e`; batch 3 design commit `177dfca25d47bac5e07b958f632496336d01433a`; batch 4 design commit `3e96f735717c3ea847ee4051f228342555a0c518`. Each committed config precedes its own first outcomes. Config hashes and every event are retained in the JSON artifacts.

Binance Spot native eight-hour ETHUSDT/SOLUSDT/LINKUSDT with matched BTC, 2020-08-11T00:00Z through 2026-09-30T16:00Z, 6,726 bars per symbol. This panel is already spent historical development data, not unseen confirmation. Source hashes match the retained audited manifest; no gap filling. 200-bar warmup, next-open execution, indicator exits plus a 30-bar cap, one full cash long sleeve per coin, no leverage or shorts. 40 bps assumed round-trip reference = 10 bps fee per side + 20 bps spread/slippage; 80 bps stress. Historical execution is not calibrated.

## Results

| Adaptation | Signals/skips/trades/pending | Net40/Net80 bps | PF40 | Sleeve ROI/DD % | Failed gates |
|---|---:|---:|---:|---:|---|
| ASDTSRockwellTrading | 5940/5397/543/0 | 116.61/76.61 | 1.41 | 421.41/-42.73 | portfolio_drawdown, net_interval_positive, placebo_tail |
| AwesomeMacd | 220/35/185/0 | 360.40/320.40 | 1.99 | 820.70/-37.73 | portfolio_drawdown, placebo_tail |
| CofiBitStrategy | 173/23/150/0 | 33.92/-6.08 | 1.14 | 10.45/-33.69 | net80_positive, all_symbols_positive, positive_year_fraction, portfolio_drawdown, net_interval_positive, excess_interval_positive |
| RSI2 | 864/419/445/0 | 32.36/-7.64 | 1.20 | 41.57/-63.39 | net80_positive, all_symbols_positive, positive_year_fraction, portfolio_drawdown, net_interval_positive, excess_interval_positive |
| CCICorrectionStrategy | 540/399/139/2 | 377.44/337.44 | 1.81 | 557.92/-61.43 | all_symbols_positive, portfolio_drawdown, net_interval_positive, excess_interval_positive, placebo_tail |
| ChandelierExit | 293/0/293/0 | 13.05/-26.95 | 1.03 | -16.92/-56.67 | net80_positive, all_symbols_positive, positive_year_fraction, leave_week_positive, portfolio_drawdown, net_interval_positive, excess_interval_positive, placebo_tail |

High development ROI is insufficient to pass failed drawdown, uncertainty, timing controls or transfer gates. No threshold is relaxed to rescue a candidate.

## Path, controls and uncertainty

| Adaptation | Mean MFE/MAE bps | Net40 interval bps | BTC excess interval bps | Placebo tail |
|---|---:|---:|---:|---:|
| ASDTSRockwellTrading | 960.0/-473.2 | -11.3,247.1 | 12.2,229.5 | 1.000 |
| AwesomeMacd | 1446.1/-725.2 | 15.3,760.5 | 101.7,674.5 | 0.662 |
| CofiBitStrategy | 468.2/-732.4 | -164.0,219.4 | -51.3,139.4 | 0.000 |
| RSI2 | 346.3/-511.8 | -49.6,112.8 | -1.3,92.5 | 0.000 |
| CCICorrectionStrategy | 1620.1/-1074.1 | -100.0,814.1 | -115.1,596.0 | 0.928 |
| ChandelierExit | 836.0/-549.3 | -120.2,145.1 | -88.5,117.9 | 0.998 |

Intervals resample contiguous four-calendar-week blocks including empty weeks, 2,000 fixed-seed replicates, descriptive batch widths 98.333%, 97.5%, and 95% for three, two, and one cells. They do not correct the cumulative adaptive search and are not confirmation tests. Entry-week clusters are not assumed independent. Same-entry-week/symbol timing placebos preserve observed holding lengths, which are endogenous; 500 replicates permit overlap and are not causal counterfactuals. Shifted +7-bar controls and matched BTC are retained. MFE/MAE use OHLC bounds, not executable fills or known high/low order. Portfolio drawdown uses eight-hour open/final-close marks and may understate intrabar risk. Compounded portfolio friction is multiplicative, whereas event means subtract fixed bps.

JSON includes all years/symbols/months, UTC-hour and overlapping fixed-session clock counts, BTC 30-bar direction / 29-return volatility bins, leave-week/symbol robustness, beta sensitivity, signal-overlap redundancy and exit reasons. ASDTS/Awesome share MACD exposure. Fixed sessions Asia [00,09), London [07,16), NY [13,22) are descriptive UTC point conventions, not DST exchange hours or filters.

## Sources and adaptations

- [ASDTSRockwellTrading](https://github.com/freqtrade/freqtrade-strategies/blob/f3340ce11f5bdf62f598522e64d1f5638eaa13f5/user_data/strategies/berlinguyinca/ASDTSRockwellTrading.py); GPL3; raw source SHA256 `58ee823e52dbf7def502c7cf069c4bca56d8198eb5037fc007856d27529e8968`.
- [AwesomeMacd](https://github.com/freqtrade/freqtrade-strategies/blob/f3340ce11f5bdf62f598522e64d1f5638eaa13f5/user_data/strategies/berlinguyinca/AwesomeMacd.py); GPL3; raw source SHA256 `8872b23514791b1e81a67e9d486e4efdd20fc08732ee5c0bf87312a82ff8a4c7`.
- [CofiBitStrategy](https://github.com/freqtrade/freqtrade-strategies/blob/f3340ce11f5bdf62f598522e64d1f5638eaa13f5/user_data/strategies/berlinguyinca/CofiBitStrategy.py); GPL3; raw source SHA256 `c565296f014ade283b684cae3ff375bd1b80c8696d7b8498b2b5915d2a6553ff`.
- [RSI2](https://github.com/jesse-ai/example-strategies/blob/7c91e0a37bf62165790120d730442e4f6eb00364/RSI2/__init__.py); MIT; raw source SHA256 `fd463da53b6ac78138a0886268f654973daa569dd2094c6aa96796a8a5015f70`.
- [CCICorrectionStrategy](https://github.com/ta4j/ta4j/blob/bc7157ed2100ff5567022c81eae5bc37c4d1640d/ta4j-examples/src/main/java/ta4jexamples/strategies/CCICorrectionStrategy.java); MIT; raw source SHA256 `36ebaf4428da06f8d3e9881df2e5c9793cebcee7d77c54af0e5b88361b86aa9f`.
- [ChandelierExit](https://github.com/hasnocool/tradingview-pine-scripts/blob/69969aeaf271b2f7b5a7632a1bde43069a0cbe26/Chandelier%20Exit%20-%20Strategy.pine); MPL2 file;GPL3 mirrorroot; raw source SHA256 `955d9e09fb9f292affcfed5802633313ddd12041c42d413d8d996c9f3924fac3`.

No upstream code copied. Independent EMA/Wilder initialization is specified; no TA-Lib/Jesse/ta4j/Freqtrade engine parity claim. ASDTS native 5m and Awesome native 1h and Cofi native 5m differ from 8h; upstream stops/ROI tables omitted explicitly in this separate hypothesis. RSI2/CCI sources do not impose bar timeframe; full warmup/cap/Spot-long/cash sizing are adaptations. Published unusual CCI exit conjunction is preserved. TDSequential/optimizedAroon/resampling examples are source exclusions, not failed backtests; prohibited Bollinger examples excluded entirely.

## Trial accounting and next step

Six new trading cells, zero parameter-search cells; earlier minimum 10 retained cells implies minimum 16 cumulative signal/model cells (at least 15 trading cells including the older exploratory variants), plus the prior source/family selection history. Every failure is permanent under its current ID. Frozen DON8/EMA8/VOL8/DV2/D4, payoff geometry, session watches and prospective protocols are unchanged. No order path or future watch was enabled.

Chandelier uses ATR22 × 3 with 22-bar close extrema and ratchetedbands. Source 5% close-loss / 20% high-gain / prior-peak 10% with 5pp drop market-close rules act only next-open; losses may exceed 5%. Source2019â€“2025datewindow andshorts are disabled, full cash sleeves / 30-bar cap / costs are adaptations. File MPL2 versus mirror root GPL3 provenance disclosed; no latest author version / native Pine parity.

Continue source selection under new immutable designs. A historical screen survivor would require independent semantics, realistic historical execution, sufficient information and genuinely untouched post-freeze confirmation before calling it viable. Repeated online searching cannot guarantee that such a candidate exists. Current search remains open; these three batches are complete.

## Reproduce

```text
python -m orderflow_edge_lab.public_bot_batch2 --config config/public_bot_batch2_v1.json --output fresh-bot-batch2.json
python -m orderflow_edge_lab.public_bot_batch2 --config config/public_bot_batch3_v1.json --output fresh-bot-batch3.json
python -m orderflow_edge_lab.public_bot_batch2 --config config/public_bot_batch4_v1.json --output fresh-bot-batch4.json
```

Batch 4 uses config/public_bot_batch4_v1.json. Outputs refuse overwrite, changed definitions and mismatched sources. Nine tests cover prefix causality, handcalculated Wilder/RSI, next-open exits, no same-decision reentry, timeout, pending equity, mutated freeze refusal, prior peak risk and adverse gap after a high-profit trigger. Full required suite and release gates are recorded in engineering evidence.
