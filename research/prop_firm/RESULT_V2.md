# Prop-firm v2: survival first (`prop-firm-v2`, declared `0f79de7`, run once): ONE CONFIGURATION WORKS

Goal: not maximum profit, but rarely breaking the rules and still getting paid within 3 and 12 months.
Firm universes are liquidity proxies (HyroTrader all coins, Breakout top 30, FTMO top 10 by dollar volume, no return
information). Phases may take up to 365 days (no time limits at these firms); 365 funded days with monthly withdrawals;
20% intraday buffer on every limit. WORKS = on both samples: challenge breach ≤ 25%, funded survival over 12 months ≥ 70%,
paid within 3 months ≥ 50%, positive EV per fee.

## The configuration that works
| HyroTrader 1-step, multi-premia blend, 0.5× risk (≈ 7% annual vol) | Development (70 coins) | Untouched (60 coins) |
| --- | ---: | ---: |
| Challenge passed | 78% | 36% |
| Challenge breached (rule hit) | 1% | 0% |
| Not finished within 365 days | 21% | 64% |
| Median days to pass | 189 | 174 |
| Funded account survives 12 months | 86% | 86% |
| Paid within 3 months (given funded) | 97% | 74% |
| Mean payout over 12 funded months | 10.9% of account | 3.5% of account |
| EV per challenge fee | 13.7× | 1.2× |

Almost never breaks a rule; the risk is slowness (6 months to pass, and on the untouched coins most attempts do not reach
+10% within a year). Once funded it usually keeps paying, but the untouched sample pays much less (3.5% a year).

## Near misses and why they fail
| Configuration | What fails | Detail (dev / untouched) |
| --- | --- | --- |
| HyroTrader 1-step blend 0.25× | EV | never breaches, survival 100%, but passes only 28% / 3% |
| HyroTrader 2-step blend 0.5× | EV on untouched | pass 73% / 20%; the extra 5% phase costs too much time |
| HyroTrader 1-step 10-coin book 0.5× | funded survival | 75% / 11% |
| Breakout Classic blend 0.75× | breach and survival | breach 12% / 39%: the 3% daily and 6% total limits are too tight for this book |
| FTMO 1-step / 2-step (10-coin universe) | funded survival | 100% on development but 0% on untouched coins |

The FTMO 0% is not 44 independent failures: overlapping starts put all funded years in the same 2025–26 stretch, and one
bad period on those 10 coins breaks the trailing / daily limits for all of them. It does show that a 10-coin book cannot
sit inside FTMO's limits through a bad period.

## Reading
- Survival needs low risk: about half the scale that maximizes EV (v1 picked 1–1.5×). At 0.5× the blend runs near 7%
  annual vol, so 4%/6% limits are rarely touched.
- Wider universes survive better: the 70-coin blend on HyroTrader works; the 10-coin FTMO and 30-coin Breakout books do not.
- The 5-coin hand-traded book never qualifies at any firm: too concentrated for the loss limits.
- Expect slow passes (about half a year) and modest, steady funded payouts, not fast money; on the untouched sample the
  payout was small. Historical, overlapping, seen data; not purchase advice; verify rules and fees before buying.
