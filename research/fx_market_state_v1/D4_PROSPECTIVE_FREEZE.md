# FX market-state v1 — prospective D4 freeze

Frozen on 2026-09-21 before the first post-freeze 12:00-16:00 UTC analysis window completes.

## Purpose

Test whether the two historical state survivors replicate prospectively without any threshold, universe, feature, target, or timestamp changes.

## Window

- Prospective D4 sessions: 2026-09-21 through 2026-10-02 inclusive.
- Eligible days: Monday-Friday UTC only.
- Universe: EURUSD, GBPUSD, USDJPY, AUDUSD.
- Source: Massive 1-minute quote-derived FX aggregates.
- Exact-minute fail-closed eligibility remains unchanged.
- Decision grid remains exactly 12:00, 12:15, ..., 15:45 UTC.

## Frozen families

### FXS-H2 volatility-expansion persistence

Unchanged from FREEZE.json:
- prior-60-return RMS baseline;
- most-recent-15-return RMS current volatility;
- trigger current_vol / baseline >= 1.50;
- future target = next-15-return RMS / same baseline;
- control = all H2-eligible grid timestamps in the same prospective evaluation slice.

### FXS-H3 Bollinger-displacement reversion

Unchanged from FREEZE.json:
- 20 exact log closes ending at t;
- z-score threshold abs(z) >= 2.0;
- target = -sign(z) * ln(close_{t+15}/close_t) * 10,000 bps.

## Prospective reporting and gates

For each family report pooled and pair-level results with exact trigger counts and sessions.

H2 D4 survival:
- >= 40 triggered observations;
- >= 8 sessions with triggers;
- pooled triggered-minus-control future-volatility ratio > 0;
- >= 3 of 4 pair effects > 0.

H3 D4 survival:
- >= 40 triggered observations;
- >= 8 sessions with triggers;
- pooled signed reversion target > 0 bps;
- pooled target>0 fraction > 0.50;
- >= 3 of 4 pair mean targets > 0 bps.

These gates were frozen before D4 outcomes.

## Evidence boundary

- Passing D4 would establish genuine prospective same-source state replication only.
- It would not establish independent-source replication, executable PnL, a trading candidate, live support, or leverage support.
- Strategy-PnL conditioning remains prohibited until D4 is complete.
- Failed D4 family IDs are not retuned or rescued.
