from __future__ import annotations

"""Outcome-blind validity adapter for strategy-discovery-v2.1.3.

This adapter starts from the audited v2.1 base runner and applies only two classes
of already-predeclared validity corrections:
1. preserve the v2.1.2 exit-fold value/index alignment repair; and
2. actually enforce the frozen minimum_symbols=8 breadth gate in both state and
   economic screening.

No family, parameter grid, symbol, date, cost case, directional rule, hold period,
or economic threshold is changed here.
"""

from pathlib import Path


BASE = Path(__file__).with_name("run_strategy_discovery_v2_1.py")
source = BASE.read_text(encoding="utf-8")

# v2.1.2: exit-fold labels must be values derived from exit timestamps while
# remaining indexed by the originating signal rows.
old_exit = "exit_folds = fold_labels(pd.DatetimeIndex(exits.dropna()), global_start, fold_days).reindex(f.index)"
new_exit = """exit_folds = pd.Series(np.nan, index=f.index, dtype=float)\n                exit_mask = exits.notna()\n                if exit_mask.any():\n                    exit_delta = (pd.DatetimeIndex(exits.loc[exit_mask]) - global_start) / pd.Timedelta(days=fold_days)\n                    exit_folds.loc[exit_mask] = np.floor(exit_delta).astype(int)"""
if old_exit not in source:
    raise RuntimeError("v2.1.3 expected exit-fold alignment target not found; refusing an unreviewed patch")
source = source.replace(old_exit, new_exit, 1)

# v2.1.3: the base config already freezes minimum_symbols=8. Record and enforce
# breadth before state translation is permitted.
old_state_gate = """state_pass = (\n                len(fold_rhos) >= int(config[\"dependence_and_trials\"][\"minimum_folds\"])\n                and med_rho > 0\n                and pos_frac >= float(config[\"state_screen\"][\"minimum_positive_fold_fraction\"])\n            )"""
new_state_gate = """state_symbol_breadth = sum(1 for data in per_symbol.values() if not data.empty)\n            state_pass = (\n                len(fold_rhos) >= int(config[\"dependence_and_trials\"][\"minimum_folds\"])\n                and state_symbol_breadth >= int(config[\"dependence_and_trials\"][\"minimum_symbols\"])\n                and med_rho > 0\n                and pos_frac >= float(config[\"state_screen\"][\"minimum_positive_fold_fraction\"])\n            )"""
if old_state_gate not in source:
    raise RuntimeError("v2.1.3 expected state gate target not found; refusing an unreviewed patch")
source = source.replace(old_state_gate, new_state_gate, 1)

old_state_row = """\"eligible_observations\": len(od), \"state_pass\": bool(state_pass)"""
new_state_row = """\"eligible_observations\": len(od), \"state_symbol_breadth\": state_symbol_breadth, \"state_pass\": bool(state_pass)"""
if old_state_row not in source:
    raise RuntimeError("v2.1.3 expected state output target not found; refusing an unreviewed patch")
source = source.replace(old_state_row, new_state_row, 1)

old_symbol_stats = """symbol_exps = [float(np.mean(v)) for v in symbol_trades.values() if v]\n                total = sum(len(v) for v in fold_trades.values())"""
new_symbol_stats = """symbol_exps = [float(np.mean(v)) for v in symbol_trades.values() if v]\n                symbol_breadth = sum(1 for v in symbol_trades.values() if v)\n                total = sum(len(v) for v in fold_trades.values())"""
if old_symbol_stats not in source:
    raise RuntimeError("v2.1.3 expected symbol statistics target not found; refusing an unreviewed patch")
source = source.replace(old_symbol_stats, new_symbol_stats, 1)

old_economic_row = """\"folds\": len(fold_exps), \"total_trades\": total,"""
new_economic_row = """\"folds\": len(fold_exps), \"total_trades\": total, \"symbol_breadth\": symbol_breadth,"""
if old_economic_row not in source:
    raise RuntimeError("v2.1.3 expected economic output target not found; refusing an unreviewed patch")
source = source.replace(old_economic_row, new_economic_row, 1)

old_economic_gate = """and total >= int(config[\"dependence_and_trials\"][\"minimum_total_trades\"])\n                    and len(fold_exps) >= int(config[\"dependence_and_trials\"][\"minimum_folds\"])"""
new_economic_gate = """and total >= int(config[\"dependence_and_trials\"][\"minimum_total_trades\"])\n                    and len(fold_exps) >= int(config[\"dependence_and_trials\"][\"minimum_folds\"])\n                    and symbol_breadth >= int(config[\"dependence_and_trials\"][\"minimum_symbols\"])"""
if old_economic_gate not in source:
    raise RuntimeError("v2.1.3 expected economic gate target not found; refusing an unreviewed patch")
source = source.replace(old_economic_gate, new_economic_gate, 1)

source = source.replace(
    '"protocol_name": "strategy-discovery-v2.1.1-low-turnover"',
    '"protocol_name": "strategy-discovery-v2.1.3-low-turnover"',
    1,
)

namespace = {"__name__": "strategy_discovery_v2_1_3_patched", "__file__": str(BASE)}
exec(compile(source, str(BASE), "exec"), namespace)

if __name__ == "__main__":
    namespace["main"]()
