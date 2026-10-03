# Prop-firm challenges (`prop-firm-v1`, declared `91d56f9`, run once): descriptive

Rules snapshot 2026-10-02 (FTMO and HyroTrader from their own sites, Breakout via Kraken; split/fee items marked
"assumed" in the config must be verified). Our historical daily net books × a risk scale, challenges started every 7 days,
daily data with a 20% intraday buffer on every loss limit, phases capped at 120 days, 180 funded days with monthly
withdrawals. EV = P(pass) × funded payout − fee, per $100 of account. Fee refunds on first payout are NOT counted
(conservative). Development = 70 coins, confirmation = 60 untouched coins.

## The pre-registered selection rule (best EV on development, checked on confirmation)
| Firm / program | Chosen book × scale | Pass dev / conf | Median days to pass | EV per $100 dev / conf | Rule says |
| --- | --- | --- | --- | --- | --- |
| FTMO 2-step | carry ×1.0 | 48% / 37% | 72 / 70 | +11.65 / +0.85 | recommended |
| FTMO 1-step | carry ×0.5 | 41% / 27% | 52 / 75 | +4.33 / +0.03 | recommended |
| HyroTrader 1-step | carry ×1.0 | 52% / 41% | 37 / 38 | +6.94 / +1.18 | recommended |
| HyroTrader 2-step | carry ×1.0 | 38% / 28% | 54 / 61 | +6.27 / +0.08 | recommended |
| Breakout Classic 1-step | carry ×0.5 | 42% / 27% | 51 / 75 | +4.36 / +0.07 | recommended |

The rule picks the carry leg everywhere, but carry alone already failed the untouched-coins holdout (t 0.9), and its
confirmation EV collapses to roughly break-even. Treat these as weak.

## The robust choice: the multi-premia blend (pass rate dev / conf, EV per $100 dev / conf)
| Firm / program | ×1.0 | ×1.5 | ×2.0 |
| --- | --- | --- | --- |
| **FTMO 2-step** | 35% / 18%, +2.0 / +1.2 | **46% / 36%, +4.5 / +3.0** | 47% / 37%, +7.1 / +1.6 |
| FTMO 1-step | 35% / 29%, +2.3 / +1.1 | 48% / 32%, +2.0 / −0.2 | 50% / 28%, +1.5 / −0.5 |
| **HyroTrader 1-step** | **41% / 31%, +3.0 / +1.7** | 50% / 40%, +6.0 / +1.0 | 55% / 38%, +3.3 / 0.0 |
| HyroTrader 2-step | 33% / 18%, +1.6 / +0.8 | 38% / 25%, +3.9 / +1.0 | 42% / 20%, +1.6 / −0.2 |
| Breakout Classic 1-step | 35% / 28%, +2.3 / +1.1 | 49% / 30%, +2.0 / −0.2 | 48% / 29%, +1.5 / −0.5 |

Trend alone passes rarely (≈10–30%) and has negative EV everywhere: 10% targets need months at its volatility.

## Reading
- Best robust fit: **FTMO 2-step with the blend at 1.5× risk** (about 36–46% pass, positive EV on both samples: roughly
  +$3,000–4,500 per $100k challenge after the fee) and **HyroTrader 1-step with the blend at 1×** (31–41% pass, +$1,700–3,000).
- Static 10% max loss with a 5% daily limit (FTMO 2-step) suits a diversified, low-drawdown book; tight 3–4% daily and
  6% total limits (Breakout, HyroTrader) punish scaling up, so the best scale there is 1×.
- Most attempts still fail (55–65%); value comes from a minority of passes plus funded payouts. Budget for several fees.
- Practical limits: the blend trades ~70 perps long and short. HyroTrader (Bybit perps, 700+ pairs, real funding) can
  hold it; FTMO's crypto CFD list and Breakout's 62 pairs are much smaller, and CFD swap costs differ from perp funding,
  so those numbers are optimistic until rebuilt on each firm's tradable list. Consistency/best-day rules are modelled for
  FTMO only.
- Historical, seen data; challenge outcomes are path-dependent and overlapping starts are not independent. This is not
  purchase advice; verify current rules and fees on each firm's site.
