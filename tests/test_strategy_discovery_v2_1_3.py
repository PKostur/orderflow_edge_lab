from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_strategy_discovery_v2_1_3.py"
SPEC = importlib.util.spec_from_file_location("strategy_discovery_v2_1_3", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
PATCHED = MODULE.namespace


def test_protocol_identity_is_v2_1_3() -> None:
    assert PATCHED["run"].__globals__["__name__"] == "strategy_discovery_v2_1_3_patched"
    source = MODULE.source
    assert '"protocol_name": "strategy-discovery-v2.1.3-low-turnover"' in source


def test_exit_fold_alignment_fix_is_preserved() -> None:
    source = MODULE.source
    assert "exit_folds = pd.Series(np.nan, index=f.index, dtype=float)" in source
    assert "exit_delta = (pd.DatetimeIndex(exits.loc[exit_mask]) - global_start)" in source
    assert "fold_labels(pd.DatetimeIndex(exits.dropna())" not in source


def test_state_pass_enforces_predeclared_symbol_breadth() -> None:
    source = MODULE.source
    assert "state_symbol_breadth = sum(1 for data in per_symbol.values() if not data.empty)" in source
    assert 'state_symbol_breadth >= int(config["dependence_and_trials"]["minimum_symbols"])' in source
    assert '"state_symbol_breadth": state_symbol_breadth' in source


def test_economic_pass_enforces_predeclared_symbol_breadth() -> None:
    source = MODULE.source
    assert "symbol_breadth = sum(1 for v in symbol_trades.values() if v)" in source
    assert 'symbol_breadth >= int(config["dependence_and_trials"]["minimum_symbols"])' in source
    assert '"symbol_breadth": symbol_breadth' in source


def test_v2_1_3_is_gate_only_amendment() -> None:
    amendment = json.loads(
        (ROOT / "config" / "strategy_discovery_v2_1_3_amendment.json").read_text(encoding="utf-8")
    )
    base = json.loads((ROOT / "config" / "strategy_discovery_v2_1.json").read_text(encoding="utf-8"))
    assert amendment["outcomes_inspected_before_amendment"] is False
    assert amendment["superseded_v2_1_2_results_may_not_be_used"] is True
    assert base["dependence_and_trials"]["minimum_symbols"] == 8
    assert amendment["base_config"] == "config/strategy_discovery_v2_1.json"
