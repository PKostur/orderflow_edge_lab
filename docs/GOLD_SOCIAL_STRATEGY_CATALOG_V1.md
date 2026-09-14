# Gold social-strategy claim catalog v1

Status: source catalog only. A social-media claim is not evidence of an edge. Only deterministic public rules are tested directly; incomplete or discretionary systems are labeled as mechanical proxies or untestable.

## Reddit-derived claims

| Claim | Public source | Rule clarity | Research mapping |
|---|---|---|---|
| EMA 4/21 crossover on XAUUSD | Reddit XAUUSD strategy discussion describing EMA21 trend direction and EMA4/21 crossing for entries/exits | high | `reddit_ema_4_21_cross`; phase-1 uses standardized fixed holds, exact opposite-cross exit required if it survives |
| EMA50/200 + RSI14 + ATR risk | Reddit Gold EA discussion: H1 EMA50/200 crossover, RSI confirmation, ATR stop/target | medium | `reddit_ema_50_200_rsi_atr`; phase-1 fixed-horizon proxy, exact ATR path test required if it survives |
| Previous-day high/low rejection | Reddit high-win-rate discussions recommending reactions/rejections at PDH/PDL | medium | `previous_day_high_low_rejection` |
| London ORB + pre-London liquidity sweep | Reddit setup: define London opening range, require pre-London buy/sell-side sweep, breakout/pullback | medium | `london_orb_sweep`; M15 coarsened proxy |
| Asia/London/PDH/PDL sweep -> CHOCH -> FVG | Reddit SMC/ICT XAUUSD discussions | low/medium because CHOCH/FVG drawing is discretionary | `smc_sweep_choch_fvg_proxy` and `new_york_sweep_choch_proxy`; raw-price mechanical definitions only |
| Asia range sweep -> displacement -> FVG retrace | Reddit liquidity-sweep XAUUSD post | medium | grouped with sweep/displacement/FVG proxy family |
| Session VWAP + EMA50 + ATR expansion + RSI divergence | Reddit XAUUSD/NAS100 scalping model | medium | `vwap_ema_atr_rsi_confluence`; RSI divergence is mechanically defined from price/RSI changes |
| Turtle Soup / failed breakout reversal | Reddit XAUUSD discussions describing prior swing raid then reversal | medium/high | `turtle_soup_session_sweep`; mechanical failed-breakout definition |
| XAUUSD/XAGUSD SMT divergence | Reddit ICT discussion explicitly preferring silver as a divergence partner for gold | medium | `gold_silver_smt_reversal` plus opposite momentum control |
| HTF liquidity raid + LTF structure shift | Reddit SMC discussion: 1H/4H raid then 15m MSS/FVG | low/medium | represented by sweep/CHOCH proxy; not labeled institutional alpha |

## YouTube-derived claims

| Claim | Public source | Rule clarity | Research mapping |
|---|---|---|---|
| EMA9/21 + RSI gold scalping | YouTube gold scalping video describing EMA9/21, RSI, EMA angle/distance/momentum filtering | medium | `youtube_ema_9_21_rsi` |
| EMA21/50 + RSI14, London/NY sessions | YouTube Gold scalping video describing EMA21/50 trend confirmation and RSI14 | medium/high | `youtube_ema21_50_rsi_session` |
| Double-RSI + EMA9 + Fibonacci, marketed ~90% WR | YouTube 1-minute Gold strategy; description exposes components but not every numeric setting/anchor rule | low/medium | `youtube_double_rsi_ema9_fib_proxy`; explicitly a proxy |
| Gold Futures Turtle Soup | YouTube Gold Futures/GC walkthrough: time-based liquidity sweep, failed breakout/CISD-style confirmation | medium | `turtle_soup_session_sweep` |
| Fake-breakout Gold strategy marketed ~90% WR | YouTube claim exposes fake-breakout/confirmation theme but not complete searchable deterministic rules | low | `fake_breakout_reversal_proxy`; creator's exact system is not claimed to be reproduced |
| Buy-only Gold DCA marketed 100% WR | YouTube claim: layered buy-only / buy-the-dip system, Jan-2026 result summary | insufficient | **not directly tested** until exact layer spacing, sizing, exit and failure rules are publicly recoverable; no invented reconstruction |
| Generic ICT/SMC Gold liquidity/FVG entries | Multiple YouTube videos/live streams describing liquidity zones, MSS/CHOCH, OB/FVG, Fibonacci | low because drawings and context are discretionary | covered only by transparent raw-price sweep/structure proxies |

## Research rules

1. Marketing win rate is never a selection metric.
2. Every family enters next bar; no same-bar hindsight fills.
3. State association is evaluated before PnL.
4. Development folds are dependence clusters and all trials remain in the ledger.
5. Primary and adverse cost cases must survive.
6. Reversed-direction controls are required.
7. A proxy passing development does not validate the creator's original discretionary strategy.
8. No 2024-2025 locked holdout is opened until a candidate is frozen under the predeclared gate.
9. Leverage 2x/5x/10x is tested only after positive unlevered holdout economics.
