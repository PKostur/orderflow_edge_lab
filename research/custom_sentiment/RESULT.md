# Custom strategy + sentiment (`custom-sentiment-v1`, declared `e7bf819`, run once): ALL FIVE FAIL (two near misses)

Contaminated by design (C1 was built after the strategy zoos on the same data; blend legs fully seen): descriptive only.
Sentiment = Crypto Fear & Greed Index (snapshot `fng_history_2026_10_01.json`), value dated d-1 used for day d.

| Book | Dev Sharpe | Dev t | Dev halves | Conf Sharpe | Conf t | Result |
| --- | ---: | ---: | --- | ---: | ---: | --- |
| C1 forced-flow dip/spike with the trend (3-day hold) | 0.30 | 0.70 | 0.64 / −0.30 | **1.20** | **2.76** | fail: strong on untouched coins, weak on development |
| F1 buy extreme fear (≤ 20 until ≥ 50) | −0.19 | −0.49 | −0.41 / 0.08 | −0.24 | −0.60 | fail |
| F2 follow sentiment (7-day mean ≥ 55 long, ≤ 45 short) | 0.75 | 1.94 | 1.16 / 0.26 | 0.67 | 1.74 | near miss; all of it in bull markets |

| Overlay on the multi-premia blend | Dev blend Sharpe | Dev halves | Dev max DD | Conf blend Sharpe | Conf halves | Result |
| --- | ---: | --- | ---: | ---: | --- | --- |
| Unchanged blend | 2.09 | 2.37 / 1.86 | −14.1% | 1.388 | 1.41 / 1.37 | – |
| O1 halve trend leg at extreme greed (≥ 80) | 2.06 | 2.37 / 1.78 | −14.1% | 1.35 | 1.41 / 1.30 | fail |
| O2 halve momentum leg after panic (≤ 25) | **2.20** | 2.44 / 2.04 | **−12.8%** | 1.386 | 1.32 / 1.44 | fail by 0.002 on the untouched sample |

## Reading
- **Sentiment as a secondary input:** pausing momentum after panics (O2) helps on the development coins (Sharpe +0.11,
  shallower drawdown) and is neutral on the untouched coins. That is consistent with momentum crashes after panics, but the
  pre-registered rule required an improvement on both samples, so it fails. Braking trend at extreme greed (O1) hurts:
  greed is when trend earns most.
- **Sentiment as a standalone signal:** following sentiment (F2) is a disguised bull-market beta bet (Sharpe 1.6 in bull
  regimes, 0 in bear); buying extreme fear (F1) loses. Contrarian sentiment does not work at daily horizons in crypto.
- **Custom forced-flow strategy (C1):** trading with the trend after volume-confirmed shocks is positive in every regime on
  the untouched coins (t 2.76) but weak on the development coins (t 0.70), so it is inconsistent. Its exposure is small
  (in the market 22% of days, drawdown about −1%), which also makes it a poor blend leg under inverse-vol weighting.
- Nothing is adopted. C1, F2 and O2 are the only candidates worth a forward-only watch, labelled exploratory because none met
  its registered bar.
