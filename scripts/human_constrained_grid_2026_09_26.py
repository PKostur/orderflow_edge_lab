"""Human-constrained optimization grid for the crypto trend core (descriptive).

Selection is pre-stated: choose by train Sharpe (2023-03-01..2024-12-31) only,
then report test (2025-01-01..2026-09-12) for every configuration.
Inputs: pickled 1h frames and funding in %TEMP% (see the session log).
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
import itertools
import json
import os
import pickle
import sys

import pandas as pd

from orderflow_edge_lab.human_execution import HumanPlan, simulate
from orderflow_edge_lab.trend_portfolio_forward import summarize

TRAIN = ("2023-03-01", "2025-01-01")
TEST = ("2025-01-01", "2026-09-12")


def _load():
    tmp = os.environ["TEMP"]
    return (pickle.load(open(f"{tmp}/h1.pkl", "rb")), pickle.load(open(f"{tmp}/fees.pkl", "rb")),
            pickle.load(open(f"{tmp}/funding.pkl", "rb")))


def run(params: dict) -> dict:
    h1, fees, funding = _load()
    plan = HumanPlan(**params)
    r = simulate(h1, fees, plan, funding=funding, start="2023-03-01T00:00:00Z")
    d = r["daily_returns"]
    out = {"params": {k: (list(v) if isinstance(v, tuple) else v) for k, v in params.items()}}
    for name, (a, b) in (("train", TRAIN), ("test", TEST)):
        seg = d[(d.index >= pd.Timestamp(a, tz="UTC")) & (d.index < pd.Timestamp(b, tz="UTC"))]
        s = summarize(seg, nw_lags=5)
        out[name] = {k: s[k] for k in ("annualized_sharpe", "newey_west_t", "mean_daily_bps", "max_drawdown", "days")}
    out["trades_per_week"] = r["trades_per_week"]
    out["fees_and_slippage_pct_per_year"] = r["fees_and_slippage_pct_per_year"]
    out["funding_pct_per_year"] = r["funding_pct_per_year"]
    return out


def grid() -> list[dict]:
    rows = []
    for k, buf, strat, ex, alloc in itertools.product(
        (3, 5), (0, 2), (("DON8", "EMA8"), ("DON8",), ("EMA8",)), ("market", "limit"), ("invvol", "mvo_shrunk")
    ):
        rows.append({"checkins_local": (9, 15, 21), "max_coins": k, "buffer": buf, "strategies": strat,
                     "execution": ex, "allocation": alloc})
    return rows


if __name__ == "__main__":
    out_path = sys.argv[1] if len(sys.argv) > 1 else "artifacts/human_grid.json"
    with ProcessPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(run, grid()))
    json.dump(results, open(out_path, "w"), indent=1, default=float)
    print("done", len(results))
