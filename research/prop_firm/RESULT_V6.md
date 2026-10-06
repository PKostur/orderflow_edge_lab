# Prop-firm v6: fastest first payout (`prop-firm-v6`, declared `8a89bcd`, run once)

Time from buying the first challenge to the first payout of at least 1% of the account, counting failed challenges and
funded accounts that breach before paying (renewal model). Payout rules: HyroTrader on-demand, max 5% of balance per
payout; Breakout on-demand; FTMO first reward after 14 days (assumed, verify). Values development / untouched.

## Fastest per firm
| Firm | Pair (challenge + funded) | Expected days to first payout | Expected fees to first payout | Funded → first payout (median) | Pays before breaching | Funded 12-month survival | First-year payouts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| HyroTrader 1-step | BTC gamble 2× + sprint 1.5× then 0.75× | **108 / 112** | 1.65% / 1.73% | 4 / 6 days | 97% / 98% | 97% / 98% | 15.4% / 7.9% |
| HyroTrader 1-step (confirmed on independent coins) | **constant-vol blend + 1× headroom** | 118 / 175 | 1.14% / 1.85% | 5 / 4 days | 96% / 95% | 81% / 100% | 16.0% / 8.6% |
| HyroTrader 1-step (confirmed) | blend 3× profit lock + 1× headroom | 114 / 189 | 0.97% / 1.67% | 4 / 2 days | 98% / 95% | 84% / 100% | 16.2% / 7.8% |
| Breakout Classic | BTC gamble 2× + sprint | 155 / 146 | 1.71% / 1.65% | 5 / 7 days | 91% / 93% | 85% / 76% | 10.8% / 6.7% |
| Breakout Classic (confirmed) | constant-vol blend + 0.75× headroom | 183 / 159 | 2.07% / 2.48% | 9 / 4 days | 100% / 98% | 80% / 66% | 9.8% / 6.5% |
| FTMO 2-step | BTC gamble 2× + 1× headroom | 219 / 151 | 2.01% / 1.35% | 15 / 19 days | 88% / 98% | 61% / 68% | 8.2% / 7.9% |

## Reading
- **Once funded, the first payout comes within about a week** at the on-demand firms (HyroTrader, Breakout): 95–100% of
  funded accounts reach +1% before any breach. The 14-day wait makes FTMO slower (15–20 days).
- **The challenge is the bottleneck:** about 90% of the total time is spent getting funded (including retries).
- **Fastest overall: HyroTrader, about 3.5–6 months and 1–2% of the account in fees to the first payout.** The very fastest
  pair starts with a no-edge BTC challenge, but its two samples share one BTC path, so the confirmed choice is the
  constant-vol blend challenge (C05) or the 3× profit-lock challenge (C13), followed by 1× with headroom scaling.
- **Funded risk trade-off:** 1× with headroom pays first fastest and pays most in year one, but its survival is 81–84% on
  development; 0.75× keeps survival near 100% for a few days' later first payout.
- A first payout within weeks of starting is not realistic without luck: even the fastest approach needs ~3.5 months on
  average because most challenge attempts fail first.
- Historical, seen data; several combinations per firm; not purchase advice; verify payout rules before buying.
