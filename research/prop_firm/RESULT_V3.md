# Prop-firm v3: risk-management policies (`prop-firm-v3`, declared `56684db`, run once)

Fixed grid of 16 policies per firm (challenge risk 0.75× or 1×, funded risk 0.5×; headroom scaling on/off; daily vol guard
on/off; 3% withdrawal cushion on/off) vs the v2 baseline (constant 0.5×). Same rules, universes, buffer and caps as v2.
Values are development (70 coins) / untouched (60 coins).

## Best policy per firm (all "work" and "improve" on both samples)
| Firm | Policy | Pass | Breach | Median days to pass | Funded 12-month survival | Paid within 3 months | Payout over 12 funded months | EV per fee |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **HyroTrader 1-step** | challenge 1×, headroom scaling, funded 0.5× | **93% / 55%** | 1% / 0% | **124 / 101** | **100% / 100%** | 91% / 73% | 11.3% / 3.8% | 17.1× / 2.6× |
| HyroTrader 1-step (v2 baseline) | constant 0.5× | 78% / 35% | 0% / 1% | 184 / 171 | 86% / 88% | 97% / 77% | 11.0% / 3.7% | 13.7× / 1.2× |
| Breakout Classic 1-step | challenge 0.75×, headroom, funded 0.5× | 65% / 38% | 3% / 4% | 180 / 147 | 100% / 80% | 82% / 60% | 6.3% / 2.8% | 7.2× / 1.1× |
| FTMO 2-step | challenge 1×, headroom, funded 0.5× | 29% / 33% | 18% / 8% | 211 / 140 | 100% / 100% | 100% / 93% | 5.6% / 5.8% | 2.0× / 2.5× |

Breakout and FTMO did not work at all in v2; with headroom scaling both now do.

## What each lever did
- **Headroom scaling (cut risk to 1/2 then 1/4 as equity nears the max-loss floor): the main win.** It allows full risk in
  the challenge (faster, more passes) while breaches stay near zero, and lifts funded survival to 100% in almost every case.
- **Phase-aware risk (challenge 1× / funded 0.5×):** most of the speed gain: 6 months to pass becomes about 4.
- **Daily vol guard:** almost no effect; the blend's daily volatility is already well inside the daily limits.
- **3% withdrawal cushion:** raises survival when headroom scaling is off, but delays payouts (paid within 3 months drops
  from ~90% to ~50–75%); with headroom scaling on it is unnecessary.

## Caveats
- 16 policies tried on seen data; the winners agree across both samples and the rules were set a priori, but this is still
  descriptive. Overlapping starts are not independent.
- The untouched sample still pays modestly (≈ 4% of the account a year at HyroTrader); the edge is reliability, not size.
- Headroom scaling must be followed exactly: compute distance to the max-loss floor each day and resize.
- Not purchase advice; verify rules and fees before buying a challenge.
