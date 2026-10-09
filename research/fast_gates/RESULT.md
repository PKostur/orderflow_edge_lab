# fast-gates-v1: result so far (2026-10-03)

Config: `config/fast_gates_v1.json` (declared `868fdcc`, thresholds frozen `7a07d46`, both before 2026-10-05).

## G3 venue replication (run once): MIXED

Frozen multi-premia-v1 rules, 2020-06-01 to 2026-09-12, 20 bps round trip. MEXC reference recomputed on the same coins.

| Venue | Coins | S1 trend | S2 XS mom | S3 XS carry | S4 blend | S4 t | MEXC S4 (same coins) | Daily corr | Pass |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Binance (prices + funding) | 70 | 1.22 | 0.03 | 0.52 | **1.05** | 2.31 | 2.09 | 0.79 | yes (just: needs ≥ 1.045) |
| Bybit (prices + funding) | 58 | 0.68 | −0.18 | 0.09 | **0.41** | 0.83 | 1.76 | 0.68 | no |

Sharpe ratios, annualized. MEXC reference legs on the Binance coin set: S1 1.17, S2 0.89, S3 1.62.

Reading (descriptive):
- The trend leg replicates on Binance prices (1.22 vs 1.17). The two cross-sectional legs do not: S2 momentum goes from 0.89 to 0.03, S3 carry from 1.62 to 0.52 (annual return 53% to 15%).
- The Binance run and the MEXC reference use the **same Binance funding series**; only prices differ. So the missing carry/momentum return comes from MEXC price paths.
- Likely mechanism (unverified): the development backtest paired MEXC prices with Binance funding. MEXC perp prices drift with MEXC's own basis and funding, so a long-low-funding/short-high-funding book on MEXC prices may collect MEXC basis drift without paying MEXC funding. The forward watches use MEXC funding with MEXC prices, so they are not affected; the development Sharpe 2.09 and the untouched-coins holdout (1.39), built the same way, may be overstated.
- Bybit coverage defect: 12 large coins (incl. XRP, BCH, ETC, UNI) failed to download (transient errors swallowed), so Bybit ran on 58 coins and a shorter window. The registered verdict stands; the Binance row is the cleaner test.

## G1, G2

Start 2026-10-05; evaluated daily in `multi-premia-blend-v1.yml` (`fast_gates_report.json`). Pre-start calibration: paper vs V_ALL correlation 0.999, TE 0.34%/yr; both books −1.6% to −1.8% over 2026-04-05 to 2026-10-03.

## funding-source-check-v1 (declared `ffd8628`, run once 2026-10-06)

Same MEXC prices, two funding series: A = Binance (how the development and holdout runs were built), B = MEXC (how the forward watches run). MEXC funding history only starts 2025-04-15, so the window is 2025-06-01 to 2026-09-12 (~15 months). Annualized Sharpe ratios:

| Sample | S1 trend A→B | S2 mom A→B | S3 carry A→B | S4 blend A→B | S4 return A→B | B−A t | Reading |
|---|---|---|---|---|---|---:|---|
| Development, 70 coins | 0.42→0.40 | 0.07→0.04 | −0.50→−0.56 | 0.26→0.19 | 2.2%→1.6% | −0.41 | NOT_MATERIAL |
| Untouched, 60 coins | 0.65→0.56 | 0.99→0.97 | **1.69→−0.18** | **1.60→0.67** | 14.9%→5.9% | −2.20 | **MATERIAL** |

MEXC vs Binance funding correlation per coin (median): 0.83 development, 0.76 untouched. Only the crash guard for 3 untouched coins without Binance funding (CRO, BP, MNT) was fixed between the two runs; the development numbers were identical in both.

Reading (descriptive):
- On the untouched coins, carry that paid in the Binance-funding construction (34%/yr) is gone with the venue's own funding (−4%/yr), and the blend loses about 60% of its return. The holdout PASS (Sharpe 1.39) leaned on that construction and is **not decision-grade**.
- On the development coins, the blend was weak in this window under either funding (Sharpe 0.2–0.3), so the funding swap changes little there; the G3 gap on those coins comes from price paths.
- Trend (S1) is robust to both checks. The forward watches already use MEXC prices with MEXC funding, so they are the clean test and continue unchanged.

## hyperliquid-venue-check-v1 (declared `4169095`, run once 2026-10-09): FAIL

Frozen blend rules on Hyperliquid prices + Hyperliquid funding (64 of 70 coins), vs the development construction (MEXC prices + Binance funding) on the same coins.

| | S1 trend | S2 XS mom | S3 XS carry | S4 blend | S4 t | S4 return/yr |
|---|---:|---:|---:|---:|---:|---:|
| Hyperliquid (consistent venue) | 0.65 | 0.76 | **−0.19** | **1.09** | 1.94 | 9.6% |
| Reference (MEXC + Binance funding) | 1.19 | 0.98 | 1.82 | 2.25 | 4.78 | 30.5% |

Annualized Sharpe ratios over each source's full period. On the 1,097 common days (2023-09-11 to 2026-09-11) the S4 figures are Hyperliquid 1.09 (t 1.94) and reference 2.27 (t 3.67). The pass rule needed Sharpe ≥ 0.5 × 2.27 = 1.13 and t ≥ 2.0, and the result missed both narrowly. Daily S4 correlation is 0.81.

Reading (descriptive): third consistent-venue test, same pattern. Carry disappears whenever prices and funding come from the same venue (Binance 0.52, MEXC-funding check −0.18 on untouched coins, Hyperliquid −0.19). What remains, mostly trend plus some momentum, is a Sharpe of about 1, not 2. The blend's historical 2.09 is not supported.
