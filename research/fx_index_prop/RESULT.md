# FX and stock indices for prop firms (`fx-index-prop-v1`, declared `b19b6f8`, run once): NOT A BETTER FIT

10 FX pairs + 10 stock indices (Yahoo daily, as FTMO-style CFDs), slow literature-standard rules, costs 3 bp (FX) / 4 bp
(indices) round trip, 5%/yr financing on index longs (FX swaps not modelled). Time split: development 2006–2015,
confirmation 2016–2026.

| Book | Dev Sharpe | Dev t | Conf Sharpe | Conf t | Annual vol | Max DD (conf) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| FX time-series momentum (1/3/6/12 m) | 0.37 | 1.17 | −0.61 | −2.06 | 4% | −26% |
| Index time-series momentum | −0.30 | −0.92 | −0.32 | −0.96 | 6% | −28% |
| Indices long, vol-targeted (after financing) | −0.03 | −0.09 | 0.19 | 0.54 | 8% | −26% |
| Index RSI(2) dip buying above the 200-day | 0.45 | 1.42 | 0.26 | 0.83 | 3% | −12% |
| FX cross-sectional momentum | 0.56 | 1.82 | −0.23 | −0.77 | 6% | −24% |
| Equal-risk FX + index blend | 0.30 | 0.88 | −0.17 | −0.53 | 3% | −12% |

No book passes (needed dev t ≥ 2 and confirmation t ≥ 1.5).

## Prop-firm careers (FTMO 2-step and 1-step, 24 months, as prop-firm-v7)
The blend never passes a challenge in either period at any tested scale: with ~1% a year of return on ~3% volatility it
cannot reach +10% within 12 months even at 3× (and the vol guard caps risk anyway). Each career buys two challenges and
loses about 1.1% of the account in fees. No configuration had a net-positive majority.

## Reading
- After costs and CFD financing, slow FX/index trend, momentum, dip-buying and the equity premium give too little edge
  (Sharpe −0.6 to +0.6) over 2006–2026, and what looked positive in 2006–2015 faded after 2016.
- For prop firms the problem is twofold: no reliable edge, and too little volatility-adjusted return to hit a +10% target in
  a reasonable time. Crypto (more dispersion, real momentum and carry premia) remains the better fit: the crypto blend at
  FTMO earned about +7% net over 24 months and +18–36% at HyroTrader (prop-firm-v7).
- Not tested: FX carry (needs interest-rate history) and intraday FX/index strategies (need intraday data and much lower costs).
