# Kronos zero-shot (`kronos-v1`, declared `51964b7`, run once): FAILS

Kronos-small (pinned weights, see `pins.json`), zero-shot, 400 × 8h bars of context, 21-bar (7-day) forecast,
5 sampled paths. Window 2024-07-01 to 2026-09-12, after Kronos's June-2024 training cutoff. 114 weekly rebalances,
70 development + 60 untouched coins. 20 bps, funding proxy.

| Sample | K1 Sharpe | t | Halves | Max DD | Rank IC (t) | Corr. with momentum | Momentum Sharpe (same window) | Blend 3→4 legs |
| --- | ---: | ---: | --- | ---: | --- | ---: | ---: | --- |
| Development (70) | −1.09 | −1.49 | −2.72 / 0.28 | −62% | −0.011 (−0.58) | −0.75 | 0.66 | 1.90→1.48 |
| Untouched (60) | −0.52 | −0.85 | −0.64 / −0.39 | −33% | −0.015 (−0.88) | −0.71 | 0.34 | 1.19→1.01 |
| Pooled (130) | −1.33 | −1.93 | −2.38 / −0.32 | −53% | −0.018 (−1.16) | −0.76 | 0.83 | – |

Volatility diagnostic (K2): Kronos's predicted move ranks next-week volatility worse than plain trailing 30-day volatility
on both samples (rank correlation 0.20 vs 0.27).

## Reading
- No forecasting skill for next-week returns (rank IC ≈ 0, slightly negative) and no edge after costs.
- Its rankings are strongly **anti-momentum** (correlation −0.75): the model mostly predicts that recent winners give back and
  losers recover. In crypto that is the wrong bet (see the strategy zoos), so the book loses where momentum earns.
- Its volatility forecasts are worse than the naive trailing-vol baseline.
- Consistent with the paper's caveat: price-forecast accuracy does not translate into crypto cross-sectional returns at a
  weekly horizon with costs. No forward watch is registered (nothing passed). Fine-tuning is not attempted: it would
  require training on our data and reintroduce leakage.
