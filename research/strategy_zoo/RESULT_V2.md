# Strategy zoo v2 (`strategy-zoo-v2`, declared `e804ea1`, run once): ALL FIVE FAIL

Same samples, costs (20 bps), halves, regimes and pass rules as zoo v1. Deviation from the declaration: the two 8h books
(Y2, Y3) are charged trading costs but not funding (about 1 bp per 8h bar held); costs dominate them either way.

| Family | Dev Sharpe | Dev t | Dev halves | Dev max DD | Conf Sharpe | Conf t | Blend 3→4 (dev / conf) |
| --- | ---: | ---: | --- | ---: | ---: | ---: | --- |
| Y1 correlation pairs (z-score 2 / 0.5) | −0.79 | −2.18 | −0.64 / −1.13 | −44% | −0.44 | −1.21 | 2.10→1.61 / 1.39→1.12 |
| Y2 US-session long (16:00 UTC bar) | −0.69 | −1.80 | −0.69 / −0.70 | −97% | −1.01 | −2.59 | 2.09→1.59 / 1.39→0.84 |
| Y3 8h cross-sectional reversal | −5.76 | −13.65 | −4.77 / −7.76 | −100% | −3.55 | −8.00 | 2.09→−0.57 / 1.39→−0.55 |
| Y4 high-vol breakout (inverse-vol sized) | 0.29 | 0.78 | 0.34 / 0.24 | −8% | 0.40 | 1.06 | 2.08→1.69 / 1.39→1.13 |
| Y5 vol-managed XS momentum | **0.83** | **2.08** | 0.52 / 1.15 | −38% | 0.55 | 1.40 | 2.09→1.88 / 1.39→1.26 |

Before costs: Y2 gross Sharpe 0.80 / 0.43 (dev / conf, +39%/yr gross) is eaten by 20 bps a day of turnover; Y3 gross is
−0.60 / +1.35 (inconsistent) and loses about 40% a year to costs.

## By regime (Sharpe, dev / conf)

| Family | CHOP | MIXED | TREND | High vol | Low vol | Bear | Bull |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Y1 pairs | −1.4 / −1.1 | 0.0 / 0.0 | −1.0 / −0.1 | −0.3 / −1.0 | −1.4 / 0.0 | −0.3 / −0.9 | −1.2 / −0.3 |
| Y2 US session | −1.9 / −2.1 | −1.8 / −1.5 | +1.3 / +0.3 | −0.4 / −0.7 | −1.2 / −1.3 | −0.8 / −1.2 | −0.7 / −0.7 |
| Y4 high-vol breakout | 0.0 / +0.5 | +0.3 / +0.7 | +0.5 / +0.2 | +0.3 / +0.1 | +0.3 / +1.1 | −0.7 / −0.1 | +1.3 / +1.1 |
| Y5 vol-managed momentum | +0.8 / +0.2 | +1.2 / +0.2 | +0.7 / +1.2 | +0.6 / +0.3 | +1.1 / +0.8 | −0.9 / +0.2 | **+2.9 / +1.0** |

## Reading
- Nothing passes. Y5 passes development (t 2.08) but misses confirmation (t 1.40), and it is no better than the plain
  momentum leg already in the blend (0.90 dev), so volatility management adds nothing here.
- Pairs trading loses: crypto pairs that were correlated keep diverging rather than reverting, including in chop,
  the regime where it was expected to work.
- Intraday (8h) ideas are killed by costs at 20 bps; US-session drift exists gross but is small and trend-dependent.
- Y4 is harmless but tiny (drawdown −8%, Sharpe 0.3–0.4), with its return in bull markets.
- Across both zoos (12 families), no new premium survives, and no family works in choppy markets. The multi-premia blend
  stays as is; the forward watches remain the only route to new evidence.
