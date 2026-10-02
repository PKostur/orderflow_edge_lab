# Canonical accounting version 2

The legacy `run_backtest` remains unchanged. `run_canonical_backtest` is a development accounting model, with its version recorded in each report.

Signals execute at the next open. The final available open is a liquidation boundary; no new target is executed there. Each interval closes an old opposite-side episode, charges entry or same-side resizing costs, then applies the weighted open-to-open price return. Each cost multiplies the equity remaining at that event. A reversal sizes the new exposure on equity after the old exit cost. Same-side weight changes remain in one trade episode.

The product of episode net-return factors must equal terminal equity. A failed reconciliation raises an error. Nonpositive equity is rejected pending an explicit bankruptcy model. Costs are proportional to changes in normalized exposure; this is a bar-weight model, not a contract-level fill or funding simulator. Summed cost bps describe normalized turnover burden, not cash fees divided by starting capital. MFE/MAE describe unweighted price excursions.

Version 1 used different compounding conventions in its trade ledger and equity path at reversals. Its previously reported canonical return estimates are superseded and must be regenerated. Legacy compatibility results and frozen strategy definitions are unaffected.
