# MEXC strategy-by-session audit

Date: 2026-09-22

Source artifact:

* GitHub Actions run: 35724999358, Continuous Order-Flow Discovery.
* Artifact: orderflow-discovery-report.
* Cumulative condition aggregate: 154,130 evaluated observations.
* Capture span: 2026-09-12 19:20 UTC through 2026-09-22 12:27 UTC.
* Independent capture batches: 84.
* Symbol: ENA_USDT.
* BTC context: BTC_USDT.
* Families: cvd, book, microprice, aligned, aligned_btc.
* Horizons: 5s, 15s, 30s.
* Cost assumptions: 4 bps and 8 bps round trip.

Named session regimes are reconstructed causally from each signal's original observation timestamp using the frozen trading-session-research-v1 definitions.

## Coverage

| Exclusive regime | Evaluated observations | Independent batches |
|---|---:|---:|
| Asia | 34,298 | 24 |
| Asia + London | 5,660 | 6 |
| London | 16,248 | 10 |
| London + New York | 29,252 | 13 |
| New York | 42,614 | 20 |
| Off-session | 26,058 | 17 |

Counts include both fee assumptions, all families and all horizons.

## Main result

Session conditioning changes relative performance but does **not** rescue the existing order-flow families.

At 4 bps round-trip friction, every sufficiently sampled family x horizon x session cell remains negative on average.

The best session cell for each family/horizon is shown below.

| Family | Horizon | Best exclusive session | Mean net bps | Observations | Batches |
|---|---:|---|---:|---:|---:|
| aligned | 5s | London | -2.831 | 69 | 9 |
| aligned | 15s | London + New York | -3.974 | 200 | 13 |
| aligned | 30s | London | -4.257 | 67 | 9 |
| aligned_btc | 5s | Asia | -3.649 | 87 | 14 |
| aligned_btc | 15s | Asia | -4.592 | 85 | 14 |
| aligned_btc | 30s | Asia + London | -1.999 | 11 | 4 |
| book | 5s | New York | -4.803 | 1,893 | 20 |
| book | 15s | London | -5.008 | 759 | 10 |
| book | 30s | Asia | -4.415 | 1,582 | 24 |
| cvd | 5s | London | -4.658 | 558 | 10 |
| cvd | 15s | Asia + London | -4.346 | 189 | 6 |
| cvd | 30s | London + New York | -4.345 | 1,176 | 13 |
| microprice | 5s | London | -4.375 | 1,313 | 10 |
| microprice | 15s | London | -4.279 | 1,297 | 10 |
| microprice | 30s | Asia + London | -4.125 | 446 | 6 |

At 8 bps round-trip friction all of these cells are more negative.

## Session market state inside evaluated signals

Aggregating all 4 bps evaluated observations provides a useful description of the state in which signals were firing.

| Regime | Mean gross signal return | Mean net | Avg spread | Avg 15s local range |
|---|---:|---:|---:|---:|
| Asia | -0.65 bps | -4.65 | 1.28 bps | 16.90 bps |
| Asia + London | -0.89 | -4.89 | 1.42 | 12.46 |
| London | -0.87 | -4.87 | 1.25 | 15.57 |
| London + New York | -0.73 | -4.73 | 1.34 | 19.43 |
| New York | -0.89 | -4.89 | 1.38 | 18.86 |
| Off-session | -1.10 | -5.10 | 1.22 | 13.88 |

The London-New York and New York regimes contain the largest local movement, but this does not translate into positive fixed-horizon signal expectancy.

This reinforces the distinction found in the 15-minute market study: high volatility/liquidity is not automatically directional edge.

## Directional travel finding

Splitting the aligned families by direction reveals one development pattern worth tracking.

For **aligned_btc short signals in the exclusive Asia regime**, gross fixed-horizon return grows with time:

| Horizon | Observations | Batches | Gross mean | Net mean at 4 bps |
|---|---:|---:|---:|---:|
| 5s | 56 | 11 | +1.23 bps | -2.77 bps |
| 15s | 54 | 11 | +2.74 bps | -1.26 bps |
| 30s | 52 | 11 | +5.19 bps | +1.19 bps |

The 30-second cell has:

* 52 observations.
* 11 independent batches.
* 50.0% net win rate.
* Profit factor about 1.14.
* Average winner about +19.80 bps.
* Average loser about -17.41 bps.
* Constant-notional cumulative result about +62.06 bps.

This initially looks like the type of condition where price travels farther after the signal.

### But the path is not robust

The +62 bps endpoint is dominated by one capture episode.

Per-batch behavior:

* 3 of 11 batches are positive.
* The September 21 Asia batch alone contributed about +243 bps.
* September 22 subsequent Asia batches gave back about -97 bps.
* Sequential max drawdown is about -201 bps.

Per-calendar-day behavior:

* 1 of 6 represented days is positive overall.
* September 21 is the only strongly positive day.

At 8 bps round-trip friction, the same 30-second gross mean becomes approximately -2.81 bps net.

Therefore this is **not** a promotable Asia-short edge.

## Interpretation

Session is useful as a state variable, but it should not be used as a standalone strategy filter yet.

The evidence currently says:

1. The existing short-horizon order-flow families remain uneconomic after realistic costs across every major session.
2. London-New York and New York contain more local movement, but current signals fail to capture that movement directionally.
3. Aligned BTC-confirmed shorts during Asia show a coherent 5s -> 15s -> 30s favorable travel pattern.
4. That Asia-short pattern is episodic rather than batch-consistent and is not cost-robust.
5. A useful future session-conditioned strategy likely needs an additional regime variable beyond the clock: volatility state, BTC direction/alignment, spread efficiency, local displacement, or another factor explaining why September 21 behaved differently from the other Asia batches.

## Next research action

Do not freeze an Asia-only candidate from this inspected sample.

Instead:

1. Keep collecting independent MEXC batches with the new named session regime.
2. Track session x direction travel profiles automatically.
3. For the Asia short aligned/aligned_btc subset, compare positive versus negative batches using only pre-signal variables:
   * spread;
   * local range-to-spread;
   * absolute return-to-spread;
   * rolling trade count;
   * signal strength;
   * BTC flow alignment;
   * BTC local direction/volatility if available.
4. Look specifically for a factor that separates the September 21 high-travel batch from the losing Asia batches.
5. If such a factor is simple and repeats across independent batches, create a new session-conditioned candidate ID and freeze it before future validation.

No live or leverage authorization follows from this analysis.
