# FX market-state v1 — independent-source Dukascopy freeze

Frozen on 2026-09-21 before any Dukascopy H2/H3 replication result is inspected.

## Source

- Independent provider: Dukascopy historical FX data.
- Current official distribution: requester-pays S3 bucket `cfg-public-proper-wallaby` in `eu-west-1`.
- Universe remains exactly EURUSD, GBPUSD, USDJPY, AUDUSD.
- Historical windows remain exactly:
  - D0-aligned: 2026-07-06 through 2026-07-31.
  - D3-aligned: 2026-08-03 through 2026-08-28.
- No pair substitution is allowed.

## Tick-to-minute transformation

Dukascopy bid/ask ticks are transformed into a source-independent one-minute close series as follows:

1. tick midpoint = (bid + ask) / 2;
2. minute close = midpoint of the final observed tick in that exact UTC minute;
3. a minute with no tick is missing;
4. no forward fill, interpolation, alternate timestamp, synthetic quote or Massive value may fill a missing minute;
5. all existing FX market-state exact-minute eligibility rules remain unchanged.

This transformation is frozen before source data is accessed.

## Frozen state definitions

Reuse the original `fx_market_state_v1` definitions unchanged.

### FXS-H2 volatility-expansion persistence
- 60 exact one-minute returns for baseline RMS;
- most recent 15 exact returns for current RMS;
- trigger current_vol / baseline >= 1.50;
- future target = next-15-return RMS / same baseline;
- control = all eligible grid timestamps in the same provider/window slice.

### FXS-H3 Bollinger-displacement reversion
- 20 exact log closes ending at decision time;
- z = displacement from 20-close log mean divided by sample standard deviation;
- trigger abs(z) >= 2.0;
- target = -sign(z) * ln(close_{t+15}/close_t) * 10,000 bps.

Decision grid remains exactly 12:00, 12:15, ..., 15:45 UTC Monday-Friday.

## Independent-source replication gates

Evaluate July and August separately.

H2 must satisfy in **both** windows:
- >= 60 triggered observations;
- >= 10 sessions with triggers;
- pooled triggered-minus-control future-volatility ratio > 0;
- >= 3 of 4 pair effects > 0.

H3 must satisfy in **both** windows:
- >= 60 triggered observations;
- >= 10 sessions with triggers;
- pooled signed reversion target > 0 bps;
- pooled fraction target>0 > 0.50;
- >= 3 of 4 pair mean targets > 0 bps.

No threshold or transformation may be changed after any Dukascopy result is observed.

## Current blocker

The official Dukascopy S3 bucket uses AWS Requester Pays. This environment does not have user AWS credentials or a connected AWS/S3 plugin. Therefore source acquisition is currently blocked before result inspection.

## Evidence boundary

Passing this test would establish independent-source historical state replication. It would still not establish executable PnL, a promoted trading candidate, live support or leverage support.
