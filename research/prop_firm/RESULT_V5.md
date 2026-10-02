# Prop-firm v5: 15 challenge approaches × 4 funded approaches (`prop-firm-v5`, declared `e247271`, run once)

180 combinations (3 firms); 117 meet the bar (funded 12-month survival ≥ 70% and positive 12-month net value on both samples).
Values development / untouched. Retries are counted (expected days and fees to a funded account). Banned schemes excluded.

## Challenge approaches at HyroTrader 1-step (funded phase F1 for comparability)
| Approach | Pass per attempt | Breach | Expected days to funded | Expected fees (bp of account) |
| --- | --- | --- | --- | --- |
| C15 BTC trend 3× | 34% / 33% | 66% / 67% | **81 / 84** | 170 / 177 |
| C14 BTC no-edge gamble 2× | 36% / 34% | 64% / 66% | 87 / 94 | 159 / 169 |
| **C05 blend at constant 25% vol** | 53% / 33% | 47% / 67% | **73 / 113** | 109 / 175 |
| **C13 blend 3× with profit lock at +6%** | 61% / 36% | 39% / 64% | 86 / 129 | 95 / 159 |
| C10 carry leg 1× | 74% / 58% | 26% / 42% | 87 / 165 | 79 / 100 |
| C03 blend two-speed (3× then 1×) | 67% / 42% | 33% / 58% | 97 / 145 | 86 / 138 |
| C04 blend catch-up (risk rises with time) | 77% / 45% | 23% / 55% | 105 / 200 | 76 / 129 |
| C12 blend 3× with cool-down after a bad day | 56% / 33% | 44% / 67% | 111 / 152 | 103 / 173 |
| C08 momentum leg 1× | 49% / 21% | 51% / 79% | 118 / 273 | 117 / 279 |
| **C01 blend 2× headroom (v4)** | **80% / 50%** | 16% / 48% | 119 / 205 | **72 / 117** |
| C07 blend regime-timed | 68% / 44% | 28% / 56% | 133 / 185 | 85 / 131 |
| C06 blend equity-curve filter | 77% / 47% | 15% / 38% | 146 / 301 | 76 / 124 |
| C09 trend leg 3× | 40% / 33% | 59% / 67% | 165 / 186 | 144 / 175 |
| C02 blend CPPI | 53% / 28% | 39% / 39% | 168 / 520 | 109 / 207 |
| C11 trend + momentum only | 43% / 32% | 57% / 67% | 195 / 257 | 134 / 180 |

## Funded approaches (after the C01 challenge, HyroTrader)
| Funded approach | 12-month survival | Paid within 3 months | Payout over 12 months |
| --- | --- | --- | --- |
| F1 blend 0.5× headroom (v3/v4) | 100% / 100% | 95% / 66% | 11.5% / 4.8% |
| **F4 blend 0.75× headroom** | 99% / 100% | 93% / 65% | **16.5% / 6.4%** |
| F3 equity-curve filter (0.75× / 0.25×) | 99% / 100% | 88% / 69% | 15.8% / 6.1% |
| F2 CPPI | 81% / 86% | 94% / 58% | 22.7% / 5.2% |

## Recommended combinations
| Firm | Fastest working pair | Days to funded | Fees | Funded survival | Net 12 months |
| --- | --- | --- | --- | --- | --- |
| HyroTrader 1-step | **C05 constant-vol blend + F4 0.75× headroom** | 73 / 113 | 1.1% / 1.75% | 99% / 100% | +14.5% / +5.9% |
| HyroTrader 1-step (formal rule pick) | C15 BTC trend + F3 | 81 / 84 | 1.7% / 1.8% | 92% / 100% | +10.2% / +5.0% |
| Breakout Classic | C14 BTC gamble + F4 | 119 / 119 | 1.6% / 1.5% | 90% / 80% | +8.6% / +5.1% |
| FTMO 2-step | C14 BTC gamble + F4 | 132 / 111 | 1.8% / 1.3% | 100% / 70% | +4.8% / +4.3% |

## Reading
- **Fast and cheap are different approaches.** The fastest challenges take high variance (BTC, constant 25% vol, 3× with a
  profit lock): about 2.5–4 months to a funded account but 1.1–1.8% of the account in fees. The cheapest (blend 2×,
  0.7–1.2% fees) passes more often but takes 4–7 months.
- **BTC-based challenges are fastest but weakly confirmed:** both samples use the same BTC history, so their agreement is not
  independent evidence, and their pass rate (~34%) is what a coin flip between the +10% target and the −6% limit gives.
  Among approaches confirmed on independent coins, **constant-vol blend (C05)** and **profit lock (C13)** are fastest.
- **Funded: 0.75× with headroom scaling (F4) pays about 40% more than 0.5×** with the same ~100% survival; CPPI pays most on
  development but survives only 81–86%.
- Most attempts still fail in the high-variance approaches (breach 47–67%); that is priced in through fees and retries.
- Historical, seen data; 60 combinations tried per firm, so the top of each list is optimistic. Not purchase advice.
