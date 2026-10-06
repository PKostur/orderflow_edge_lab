# Prop-firm v7: largest payouts over a 24-month career (`prop-firm-v7`, declared `41a5ae2`, run once)

Each career starts every 14 days and runs 24 months: buy a challenge (fee), retry after failures, trade funded under the
policy, withdraw per the rule, buy again after any funded breach. Net = all payouts − all fees, in % of one account.
120 policies per firm (4 challenges × 5 funded scales × 2 sizing variants × 3 withdrawal rules). Values development / untouched.

## Best per firm (p_net_positive ≥ 60% on both samples, ranked by worst-case mean net)
| Firm | Policy (challenge, funded, withdrawal) | Mean net over 24 months | Median | 10th percentile | P(net > 0) | Fees paid | Challenges bought | Funded breaches |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| HyroTrader 1-step | BTC gamble, 1.5× headroom, on-demand at +1% | 36.8% / 23.9% | 36.8 / 25.0 | 21.8 / 5.3 | 100% / 98% | 3.5 / 4.7% | 6.0 / 8.1 | 0.8 / 2.1 |
| **HyroTrader 1-step (confirmed)** | **constant-vol blend, 1.25× headroom, on-demand at +1%** | **36.5% / 18.1%** | 37.1 / 14.9 | **28.2 / 4.1** | 100% / 96% | 1.6 / 3.0% | 2.8 / 5.1 | 0.3 / 2.0 |
| HyroTrader 1-step (confirmed) | constant-vol blend, 1.5× headroom, on-demand | 36.5% / 18.1% | 35.7 / 20.9 | 23.6 / 4.2 | 100% / 100% | 2.3 / 4.4% | 4.0 / 7.5 | 1.0 / 2.5 |
| Breakout Classic | BTC gamble, 1.25× headroom, on-demand | 12.7% / 9.2% | 14.2 / 8.8 | 2.7 / 3.7 | 100% / 98% | 3.1 / 3.8% | 6.3 / 7.5 | 1.2 / 2.1 |
| Breakout Classic (confirmed) | blend 3× profit lock, 1× headroom, on-demand | 14.9% / 7.9% | 14.4 / 6.7 | 2.0 / 4.6 | 95% / 100% | 1.5 / 3.6% | 3.0 / 7.3 | 0.3 / 1.6 |
| FTMO 2-step | BTC gamble, 1× headroom, on-demand | 10.4% / 10.5% | 11.7 / 12.0 | −1.1 / 3.2 | 88% / 100% | 3.0 / 1.8% | 5.5 / 3.3 | 0.3 / 0.5 |
| FTMO 2-step (confirmed) | blend 2×, CPPI 1×, monthly | 7.4% / 6.7% | 9.7 / 0.5 | 0.8 / −2.9 | 93% / 62% | 1.5 / 1.6% | 2.8 / 3.0 | 0.0 / 0.0 |

## Reading
- **Largest payouts: HyroTrader, funded at 1.25–1.5× with headroom scaling, withdrawing as soon as profit reaches +1%.**
  About +36% (development) / +18% (untouched) of the account net over 24 months, i.e. roughly 9–18% a year, with almost
  every career net positive.
- **Withdraw early and often.** On-demand withdrawals at +1% beat monthly withdrawals almost everywhere: profit is banked
  before a breach can take it, and with headroom scaling a breach only costs a new (cheap) challenge.
- **Run the funded account harder than for survival** (1.25–1.5× instead of 0.5–0.75×): more breaches (up to ~2 per two
  years on the untouched sample) but the extra payouts outweigh the extra fees. This is the opposite of the survival-first
  answer in v2/v3, because re-buying is cheap relative to payouts.
- Breakout and FTMO pay much less (tight 3% daily loss at Breakout; 2-step plus a 10-coin universe at FTMO).
- Several accounts multiply payouts and fees, but the same strategy breaches on the same days, so risk is not diversified;
  firm allocation caps apply. HyroTrader also caps each payout at 5% of the balance (modelled).
- Historical, seen data; 120 policies per firm, so the top is optimistic (the BTC rows share one BTC path). Not purchase
  advice; verify rules, payout terms and fees before buying.

## Post-result integrity note (2026-10-06; no recomputation)
The blend-based rows above inherit the historical multi-premia data construction used by these one-shot studies. The later
pre-registered `fast-gates-v1` venue replication found only MIXED cross-venue support and identified a material venue/funding
mismatch risk in the historical blend evidence: the development/untouched blend paired MEXC price paths with Binance funding,
whereas the prospective watches use MEXC funding with MEXC prices. The historical payout numbers above are therefore scenario
outputs, not validated expected returns, and must not be used to justify leverage, buying a prop-firm challenge, promotion, or
live trading. The separately frozen `prop-paper-career-v1` watch (start 2026-10-05) is the relevant future paper test and remains
descriptive until its registered review gate.
