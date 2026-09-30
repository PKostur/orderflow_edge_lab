# Cross-market ETF v1 — terminal status

**Research ID:** `cross_market_etf_v1`  
**Branch:** `research/cross-market-etf-v1`  
**Status:** `TERMINAL_FALSIFIED_D0_ALL_FAMILIES`

This lane is closed under its frozen IDs. No threshold, ticker, direction, timing, or cost parameter may be retuned under the same family IDs.

## Frozen evidence sequence

1. Protocol frozen before ETF hypothesis PnL.
2. Calculation/timing clarifications frozen before ETF hypothesis PnL.
3. July 6–31, 2026 D0 evaluated.
4. D0 independently reacquired/recomputed from Massive and matched the recorded result.
5. Because every family failed at least one mandatory D0 survival gate, the August 3–28 D3 holdout remains sealed and must not be inspected for these IDs.

## D0 outcomes

| Family | Signals | Primary net mean | Stress net mean | Reversed control | Terminal reason |
|---|---:|---:|---:|---:|---|
| ETF_H1_ORB15_CONTINUATION | 76 | +1.2650 bps | -0.7350 bps | -5.2650 bps | Failed both-calendar-halves-positive gate; H1 first half = -5.1591 bps, second half = +7.6891 bps |
| ETF_H2_VWAP_VOL_REVERSION | 75 | +1.8367 bps | -0.1633 bps | -5.8367 bps | Failed breadth and concentration gates; only 2 positive tickers, positive PnL dominated by USO |
| ETF_H3_GAP_REVERSION | 42 | -16.3917 bps | -18.3917 bps | +12.3917 bps | Negative expectancy, loses to reversed control, insufficient breadth and concentration |

Primary friction = 2 bps round trip. Stress friction = 4 bps round trip.

## Research state

- D0: `FALSIFIED_ALL_FAMILIES`
- D3 August holdout: `SEALED_NOT_INSPECTED`
- Candidate created: **no**
- Future shadow created: **no**
- Persistent edge established: **no**
- Live execution supported: **no**
- Leverage supported: **no**
- Same-ID retuning allowed: **no**

## Interpretation

The positive pooled July means in H1 and H2 are not sufficient evidence of a transferable edge because the predeclared survival gates were designed to reject regime dependence, weak cross-ticker breadth, and single-market concentration. H3 fails directly on expectancy and control comparison.

Any future ETF work must start under a new research ID with hypotheses frozen before accessing the sealed August holdout. The sealed August data must not be used to rescue or redesign H1/H2/H3.

Canonical numeric record: `research/cross_market_etf_v1/D0_RESULT.json`.
