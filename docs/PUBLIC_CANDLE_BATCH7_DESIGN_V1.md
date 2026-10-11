# PSR13: Full Candle source-default intent, frozen before outcomes

One new mathematical adaptation, FullCandle8hDefaultIntent. The configuration defines every rule, cost, control and gate. Published default TP and SL are disabled and remain disabled; no invented timeout. Native all-NaN strategy.exit behavior is unverified. This is a declared paper mathematical port, not proof that the native Pine bot runs or reproduces these fills. Bollinger is excluded; prior definitions, artifacts, payoff geometry and prospective watches remain unchanged.

## Exact mechanics

Pinned Alorse Full Candle source uses initial1000USD,10%equity intent, EMA10 level and at most5% directional shadow. Compute shadow times100 then divide by high-low; zero range remains NaN. Seed EMA from first close; alpha2/(10+1), beta1-alpha, then two products and addition in binary64. Long requires bullish close above EMA; short requires bearish close below EMA. Spot adaptation translates original short entry to liquidation of an existing long only. Source has no fixed timeframe;8h is the user-selected adaptation.

At accepted next-open long, capture the raw8h fill-bar open. Its first permitted use is that bar's completed close. A held long exits when bullish close strictly exceeds reference plus reference times0.002, or original short geometry qualifies. Preserve multiply-then-add threshold arithmetic. Each control creates its own references and position-dependent exits. Flat close calls do not cancel pending entry; held same-direction entry does not allow re-entry at its liquidation boundary.

Use floor8(cash*0.1/(signal close*(1+sidecost))) and next-open all-or-reject affordability. Source native opening-equity sizing is different; no parity claim.1000USD becomes1000USDT under declared1:1 research accounting assumption. No borrowing, pyramiding, orders or source-option optimization. Minute OHLCV supplies full held-period excursions, next-open execution, funded BTC reference and censored cutoff marks; no price barriers exist. Gap models are therefore intentionally identical.

## Evidence and claims

Reuse the quality-selected2023-04-01 through2026-09-30 complete continuous four-symbol Binance Spot segment,240closed8h bar warmup, ETH/SOL/LINK sleeves and BTC reference. It is already-spent development history with no2022bear coverage. Costs20/40/60/80bps, all existing survival gates,500 weekly randomized-entry controls and7bar lag remain fixed. Bootstrap2000 moving4calendar-week blocks retains fixed alpha0.025,97.5% intervals conservatively for this ONE new cell; no global repeated-search statistical claim. Full trial accounting advances minimum19/20 to20trading/21signal-model cells only at registration.

A historical survivor can only start a separately frozen future-only confirmation study with adequately powered, calibrated costs and execution evidence. User's viability endpoint requires that future confirmation to pass. Never call history untouched or this candidate viable. Preserve initial narrower exclusion and subsequent precision/default-runtime corrections as auditable source-only history. No market outcomes informed these corrections.
