from __future__ import annotations

import math

import numpy as np

import run_gold_strategy_discovery_v1 as base

_real_dumps = base.json.dumps


def _clean(value):
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, np.floating):
        x = float(value)
        return x if math.isfinite(x) else None
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    if isinstance(value, tuple):
        return [_clean(v) for v in value]
    return value


def _safe_dumps(obj, *args, **kwargs):
    return _real_dumps(_clean(obj), *args, **kwargs)


base.json.dumps = _safe_dumps

if __name__ == "__main__":
    base.main()
