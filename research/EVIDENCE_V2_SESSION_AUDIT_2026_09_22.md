# Evidence v2 cross-strategy session audit - 2026-09-22

Status: **descriptive development audit only**

This report applies a frozen session audit to four strategy variants that were already robust-screening-eligible at the conservative 20 bps round-trip cost case in the existing `evidence-backed-strategies-v2` leaderboard.

The variants were chosen before session results were inspected:

| Audit ID | Family | Interval | Parameters |
|---|---|---:|---|
| EMA8 | EMA time-series momentum | 8h | fast 24, slow 96, ATR threshold 0.25 |
| DON8 | Donchian breakout | 8h | lookback 55 |
| VOL8 | volatility-scaled momentum | 8h | lookback 24, vol window 96, threshold 0.5 |
| EMA4 | EMA time-series momentum | 4h | fast 12, slow 96, ATR threshold 0 |

Source period: 2024-01-01 through 2026-09-12 on the frozen 10-symbol MEXC futures universe.

Costs: 20 bps round trip.

Session buckets are fixed UTC strategy-bar windows:

* Asia-like: 00:00-08:00 UTC.
* London plus London/New-York overlap: 08:00-16:00 UTC.
* New-York post-overlap plus late transition: 16:00-24:00 UTC.

These are coarse crypto portfolio windows, not pure exchange sessions.

## Full-period session economics

### EMA8

| Bucket | Trades | EV | PF | Positive symbols | Median 120d fold EV | Positive folds | Median MFE | Median MAE |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 00-08 | 122 | -238.3 bps | 0.65 | 40% | -235.9 | 22.2% | 700 | -824 |
| 08-16 | 109 | **+849.3** | **2.64** | 70% | **+434.3** | 55.6% | 1,066 | -648 |
| 16-24 | 111 | +364.5 | 1.70 | 60% | +81.0 | **66.7%** | 1,028 | -653 |

Year EV:

| Bucket | 2024 | 2025 | 2026 |
|---|---:|---:|---:|
| 00-08 | -113 | -592 | -58 |
| 08-16 | +1,728 | +707 | **-343** |
| 16-24 | +382 | +23 | **+835** |

Interpretation: the full-period EMA8 endpoint strongly favors 08-16, but the effect rotated in 2026. The latest year favors 16-24 instead. This is not stable enough to justify a session-conditioned EMA rule.

### DON8

| Bucket | Trades | EV | PF | Positive symbols | Median 120d fold EV | Positive folds | Median MFE | Median MAE |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 00-08 | 100 | -142.5 bps | 0.84 | 40% | +36.6 | 55.6% | 1,986 | -986 |
| 08-16 | 57 | **+1,816.6** | **3.76** | 60% | +658.9 | 62.5% | **2,613** | -814 |
| 16-24 | 73 | +537.0 | 1.66 | 60% | **+1,068.6** | **66.7%** | 1,758 | -964 |

Year EV:

| Bucket | 2024 | 2025 | 2026 |
|---|---:|---:|---:|
| 00-08 | -127 | -582 | +387 |
| 08-16 | **+3,689** | **+904** | **+596** |
| 16-24 | +1,121 | +88 | +166 |

This is the strongest session pattern in the audit. The 08-16 Donchian bucket is positive in every represented year and has clearly larger favorable excursion than the Asia bucket.

However, the sample remains only 57 trades and the result is development data. No session filter is authorized from this audit.

#### DON8 08-16 direction split

| Direction | Trades | EV | PF | Positive 120d folds | 2026 EV |
|---|---:|---:|---:|---:|---:|
| Short | 27 | +590 bps | 2.14 | **71.4%** | **+1,084 bps** |
| Long | 30 | +2,921 bps | 4.72 | 42.9% | -380 bps |

The long side explains much of the very large historical endpoint, especially in earlier years, while the short side is more fold-consistent and remained strong in 2026. This reduces, but does not eliminate, the concern that the 08-16 effect is merely a broad crypto bull-market long bias.

### VOL8

| Bucket | Trades | EV | PF | Positive symbols | Median 120d fold EV | Positive folds | Median MFE | Median MAE |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 00-08 | 713 | -20.2 bps | 0.89 | 50% | -29.3 | 33.3% | 238 | -184 |
| 08-16 | 593 | **+99.8** | **1.61** | 70% | -15.4 | 44.4% | 228 | -203 |
| 16-24 | 789 | +36.2 | 1.20 | 60% | **+36.5** | **66.7%** | 244 | -182 |

Year EV:

| Bucket | 2024 | 2025 | 2026 |
|---|---:|---:|---:|
| 00-08 | -31 | -34 | +13 |
| 08-16 | +222 | +7 | +70 |
| 16-24 | +96 | -48 | +75 |

The full-period London-block endpoint is positive, but the median 120-day fold remains negative. The more consistent bucket is 16-24, although its effect is modest. There is no clean VOL8 session candidate here.

### EMA4

| Bucket | Trades | EV | PF | Positive symbols | Median 120d fold EV | Positive folds | Median MFE | Median MAE |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 00-08 | 341 | -77.9 bps | 0.79 | 40% | -82.7 | 22.2% | 523 | -416 |
| 08-16 | 320 | +37.2 | 1.10 | 50% | +32.4 | 55.6% | **555** | -379 |
| 16-24 | 327 | **+237.2** | **1.62** | 70% | -49.2 | 33.3% | 517 | -413 |

Year EV:

| Bucket | 2024 | 2025 | 2026 |
|---|---:|---:|---:|
| 00-08 | -131 | -160 | +112 |
| 08-16 | -16 | +20 | **+124** |
| 16-24 | **+748** | +83 | **-104** |

The large 16-24 endpoint is not fold-stable and reversed in 2026. The 08-16 block is much smaller but has better fold consistency and remained positive in 2026.

Exact 4h entry-hour EV:

| Entry hour UTC | Trades | EV | PF |
|---:|---:|---:|---:|
| 00 | 186 | -184 bps | 0.53 |
| 04 | 155 | +49 | 1.14 |
| 08 | 152 | +6 | 1.02 |
| 12 | 168 | +66 | 1.18 |
| 16 | 155 | +189 | 1.53 |
| 20 | 172 | +281 | 1.68 |

The apparent 16-24 advantage therefore comes from both 16:00 and 20:00 UTC entries, but its historical stability remains weak.

## Cross-strategy conclusions

### 1. 00-08 UTC is consistently the weakest trend window

All four audited strategies have the weakest or near-weakest full-period economics in the 00-08 bucket.

This pattern is broader than the ENA-only order-flow work because it appears across ten symbols and multiple strategy families.

### 2. 8h strategies broadly favor later global-liquidity windows

All three 8h strategies perform better in 08-16 and/or 16-24 than 00-08.

However, the exact best bucket depends on the strategy and period.

### 3. Donchian 8h provides the cleanest session-state hypothesis

DON8 08-16 is the only audited bucket that combines:

* strongly positive full-period EV;
* PF well above 1;
* positive symbol breadth;
* positive majority of 120-day folds;
* positive yearly EV in 2024, 2025 and 2026;
* higher median favorable excursion;
* evidence on both long and short sides.

This is enough to justify a **new future research hypothesis**, not enough to alter the existing Donchian strategy retrospectively.

### 4. EMA session leadership rotates

EMA8 historically favored 08-16, but 2026 favored 16-24. EMA4 historically favored 16-24, but 2026 favored 08-16.

That rotation argues against a fixed generic "EMA trades best in session X" rule.

### 5. Volatility-scaled momentum has a weaker session effect

VOL8 shows positive full-sample results outside Asia, but the 08-16 result is not fold-stable. The 16-24 block is more consistent but economically modest.

### 6. Session is a strategy-state interaction, not a universal market rule

The broader project now shows different behavior by mechanism:

* Donchian breakout: strongest evidence for 08-16.
* EMA trend: session leadership rotates.
* Vol-scaled momentum: mild later-session advantage.
* Cross-sectional momentum: recent forward PnL shape differs and is highly concentrated.
* ENA order flow: London/New-York creates movement, but broad directional signals remain weak.
* Gold: has its own cross-session state structure and should remain a separate mechanism.

## Basis-convergence control

The evidence-backed 1h basis-convergence study had **zero screening-eligible variants**. It is therefore not being session-optimized. Session conditioning will not be used to rescue a family that already failed its primary economic screen.

## Next action

The only new session hypothesis justified by this audit is a **Donchian 8h / 08-16 UTC forward watch**.

It should use:

* the exact already-selected Donchian lookback 55 rule;
* the unchanged 20 bps cost assumption;
* the unchanged ten-symbol universe;
* no side exclusion;
* no parameter change;
* a future-only start after the session hypothesis is frozen;
* separate reporting of long and short contributions;
* cumulative equity path, fold/batch consistency, MFE/MAE and concentration.

The existing Donchian development result must never be counted as prospective evidence for that watch.

No current strategy is modified and no live/leverage authorization follows from this audit.
