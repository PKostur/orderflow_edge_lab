# Cross-market ETF v1 — cumulative-VWAP missing-minute clarification

Frozen before any ETF hypothesis PnL is calculated.

For ETF_H2_VWAP_VOL_REVERSION, cumulative VWAP is defined over the complete exact one-minute sequence from 09:30 ET through the signal minute. If any minute in that interval is missing, that signal timestamp is ineligible. No skipped-bar renormalization, interpolation, forward fill, substitute bar, or alternate timestamp is allowed.
