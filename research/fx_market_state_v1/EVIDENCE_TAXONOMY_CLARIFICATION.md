# FX market-state v1 — evidence-stage taxonomy clarification

This clarification changes nomenclature only; it does not change any feature, threshold, date, target, or survival gate.

The original `FREEZE.json` key named the 2026-08-03..2026-08-28 window `D2_nonoverlap_replication`. Under the repository-wide evidence taxonomy, a non-overlapping historical holdout from the **same source** is D3 historical holdout, while D2 is reserved for independent-source/same-period replication.

Therefore:

- 2026-08-03..2026-08-28 is treated and reported as **D3 historical holdout**.
- It is not independent-source replication and not genuine future OOS.
- Only the two D0-surviving families (FXS_H2 and FXS_H3) may be evaluated there.
- The originally frozen numerical gates remain unchanged.
- FXS_H1 remains dead and its August result will not be inspected.
