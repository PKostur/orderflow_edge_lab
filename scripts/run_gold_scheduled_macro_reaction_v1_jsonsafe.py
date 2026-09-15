from __future__ import annotations

"""JSON-safe launcher for the frozen Gold scheduled-macro v1 scorer.

The underlying scorer completed inference on the first Dukascopy run but failed while
serializing a pandas NaT value in an event record. This wrapper changes only output
serialization. It does not alter event construction, hypotheses, permutation tests,
FDR, gates, or any state statistic.
"""

import importlib.util
from pathlib import Path

import pandas as pd


SCORER = Path(__file__).with_name("run_gold_scheduled_macro_reaction_v1.py")
spec = importlib.util.spec_from_file_location("gold_scheduled_macro_reaction_v1_core", SCORER)
if spec is None or spec.loader is None:
    raise RuntimeError(f"could not load frozen scorer from {SCORER}")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

_core_clean = module.clean


def _jsonsafe_clean(value):
    if value is pd.NaT or value is pd.NA:
        return None
    return _core_clean(value)


module.clean = _jsonsafe_clean

if __name__ == "__main__":
    raise SystemExit(module.main())
