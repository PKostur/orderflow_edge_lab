# Prop-firm v4: fast pass, slow fund (`prop-firm-v4`, declared `089ded5`, run once)

Challenge at higher risk (headroom scaling + daily vol guard keep it inside the rules), funded at the safe v3 policy
(0.5×, headroom scaling). Retries until a pass: expected fees per funded account = fee / p, expected days = mean attempt
length / p. Values development / untouched. Rule-breaking schemes (opposite positions across accounts or firms, reverse
copy trading) were excluded: they are banned and void payouts.

## Choice per firm (fastest with positive 12-month net value and ≥ 70% funded survival on both samples)
| Firm | Challenge | Pass per attempt | Expected days to a funded account | Expected fees per funded account | Funded 12-month survival | Payout over 12 funded months | Net of fees |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **HyroTrader 1-step** | blend 3× | 61% / 36% | **86 / 129** | **0.95% of account** | 100% / 100% | 10.7% / 4.9% | +9.8% / +3.3% |
| HyroTrader 1-step | blend 2× | 80% / 50% | 119 / 205 | 0.72% | 100% / 100% | 11.5% / 4.8% | +10.8% / +3.6% |
| Breakout Classic | blend 3× | 36% / 28% | 136 / 195 | 1.39% | 100% / 98% | 7.6% / 5.3% | +6.2% / +3.5% |
| FTMO 2-step | blend 3× | 18% / 11% | 326 / 507 | 3.0% | 100% / 100% | 3.9% / 8.8% | +0.9% / +4.0% |

For $100k at HyroTrader: about $950 of fees and 3–4 months (incl. retries) to a funded account, then about $5,000–10,000
of payouts in its first funded year on these samples.

## The no-edge reference (long BTC, same risk controls, challenge only)
| Firm | Pass per attempt | Expected days to a funded account | Expected fees |
| --- | --- | --- | --- |
| HyroTrader 1-step | 38% | 79–84 | 1.5% |
| Breakout Classic | 35% | 104–107 | 1.4% |
| FTMO 2-step | 32% | 115–126 | 1.7% |

A strategy with no edge passes about as often as geometry predicts (target +10% vs loss −6%: 6/16 ≈ 37.5%), because the
challenge is close to a coin flip between two barriers. Our edge mostly lowers fees per funded account (0.6–1.0% vs 1.5%)
and, more importantly, is what makes the funded account pay. A gamble gets you funded but then has nothing to trade.

## Reading
- Fastest reliable route: **HyroTrader 1-step, blend at 2–3× in the challenge, 0.5× with headroom scaling once funded.**
  3× is fastest (≈ 3 months), 2× passes more often and costs fewer fees (≈ 4 months).
- At FTMO the 10-coin blend is slow (2-step plus a small universe); a high-volatility, rule-safe challenge approach passes
  faster there, but the funded phase still needs the blend, so FTMO is the weakest fit.
- Payouts on the untouched sample are modest (≈ 5% of the account a year). "Quick" here means months, not days: a strategy
  that promises days relies on luck or on banned exploits.
- Historical, seen data; overlapping starts; not purchase advice. Verify rules and fees before buying.
