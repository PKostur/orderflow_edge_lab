# Cross-market research wrap-up — 2026-09-21

This file closes the current non-crypto branching sprint. It does **not** introduce a new hypothesis, change any frozen threshold, inspect any sealed holdout, or promote any strategy.

## ETF lane

Research ID: `cross_market_etf_v1`  
Branch: `research/cross-market-etf-v1`  
Terminal state: **FALSIFIED_D0_ALL_FAMILIES**

Frozen D0: 2026-07-06..2026-07-31.  
Locked D3 holdout: 2026-08-03..2026-08-28.

The August holdout remains sealed because no frozen ETF family passed all mandatory D0 survival gates.

- `ETF_H1_ORB15_CONTINUATION`: pooled +1.2650 bps/signal at the 2 bps round-trip friction case, but -0.7350 bps at 4 bps and failed the predeclared calendar-half stability gate (first half -5.1591 bps, second half +7.6891 bps).
- `ETF_H2_VWAP_VOL_REVERSION`: pooled +1.8367 bps/signal at 2 bps, but -0.1633 bps at 4 bps; only two tickers were positive and positive PnL was dominated by USO, failing breadth and concentration gates.
- `ETF_H3_GAP_REVERSION`: pooled -16.3917 bps/signal at 2 bps and lost to its reversed control.

The D0 data were reacquired from Massive and recomputed after the original evaluation; the result matched. No ETF candidate or future shadow was created.

## Futures lane

Branch: `research/cross-market-futures-v1`

The one-minute futures price-transfer experiment and its market-specific historical replication are closed as falsified. In particular:

- the post-v1 NQ breakout replication averaged -5.0899 bps/signal at the primary cost case while its reversed control averaged +4.7491 bps/signal;
- the commodity reversion replication produced no eligible GC signals under the frozen exact-minute rule and CL averaged -2.3922 bps/signal.

The separate futures **order-flow** protocol is not falsified. It remains blocked because the available Massive entitlement does not provide the historical event data required for the frozen replay: causal historical Quote/BBO state is required for executable H1/H3 evaluation, and true top-10 depth history is additionally required for H2.

## Consolidated research state

- Persistent cross-market edge established: **no**
- Non-crypto candidate promoted: **no**
- Future non-crypto shadow created: **no**
- Live execution supported: **no**
- Leverage supported: **no**
- Failed IDs may be retuned: **no**
- ETF August D3 may be opened to rescue failed IDs: **no**
- Futures order-flow lane may resume only when eligible event data are available: **yes**

The appropriate next research cycle, if resumed, must use a new research ID and a pre-result freeze. The failed price/bar IDs remain dead. The existing crypto evidence chain remains separate and unchanged.
