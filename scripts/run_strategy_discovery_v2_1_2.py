from __future__ import annotations

"""Pre-outcome reliability adapter for strategy-discovery-v2.1.2.

This intentionally patches only the documented exit-fold index-alignment defect in
run_strategy_discovery_v2_1.py. The frozen family definitions, grids, dates,
symbols, costs and gates remain unchanged. Keeping the patch narrow preserves the
auditable v2.1/v2.1.1 history while ensuring exit dependence-cluster labels are
computed from exit timestamp values and retained on the originating signal index.
"""

from pathlib import Path


BASE = Path(__file__).with_name("run_strategy_discovery_v2_1.py")
source = BASE.read_text(encoding="utf-8")

old = "exit_folds = fold_labels(pd.DatetimeIndex(exits.dropna()), global_start, fold_days).reindex(f.index)"
new = """exit_folds = pd.Series(np.nan, index=f.index, dtype=float)\n                exit_mask = exits.notna()\n                if exit_mask.any():\n                    exit_delta = (pd.DatetimeIndex(exits.loc[exit_mask]) - global_start) / pd.Timedelta(days=fold_days)\n                    exit_folds.loc[exit_mask] = np.floor(exit_delta).astype(int)"""

if old not in source:
    raise RuntimeError("v2.1.2 expected exit-fold alignment target not found; refusing an unreviewed patch")

source = source.replace(old, new, 1)
source = source.replace(
    '"protocol_name": "strategy-discovery-v2.1.1-low-turnover"',
    '"protocol_name": "strategy-discovery-v2.1.2-low-turnover"',
    1,
)

namespace = {"__name__": "strategy_discovery_v2_1_2_patched", "__file__": str(BASE)}
exec(compile(source, str(BASE), "exec"), namespace)

if __name__ == "__main__":
    namespace["main"]()
