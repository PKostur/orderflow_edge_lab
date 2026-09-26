"""Session-timing and market-regime comparison for the human-constrained trend core (descriptive).

Runs the principled configuration under several check-in schedules and saves
daily return series for regime analysis.  Inputs come from the pickles written
for the grid run (1h frames, fees, funding) in %TEMP%.
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
import os
import pickle
import sys

from orderflow_edge_lab.human_execution import HumanPlan, simulate

PRINCIPLED = dict(max_coins=5, buffer=2, strategies=("DON8", "EMA8"), execution="market", allocation="invvol")
TRAIN_BEST = dict(max_coins=5, buffer=0, strategies=("EMA8",), execution="market", allocation="mvo_shrunk")

RUNS = {
    "principled_cet_09_15_21": {**PRINCIPLED, "sessions": (("Europe/Berlin", 9), ("Europe/Berlin", 15), ("Europe/Berlin", 21))},
    "trainbest_cet_09_15_21": {**TRAIN_BEST, "sessions": (("Europe/Berlin", 9), ("Europe/Berlin", 15), ("Europe/Berlin", 21))},
    "principled_utc_00_08_16": {**PRINCIPLED, "sessions": (("UTC", 0), ("UTC", 8), ("UTC", 16))},
    "principled_tokyo_open": {**PRINCIPLED, "sessions": (("Asia/Tokyo", 9),)},
    "principled_london_open": {**PRINCIPLED, "sessions": (("Europe/London", 8),)},
    "principled_newyork_open": {**PRINCIPLED, "sessions": (("America/New_York", 10),)},
    "principled_london_newyork": {**PRINCIPLED, "sessions": (("Europe/London", 8), ("America/New_York", 10))},
    "principled_all_three_opens": {**PRINCIPLED, "sessions": (("Asia/Tokyo", 9), ("Europe/London", 8), ("America/New_York", 10))},
    "principled_cet_09_only": {**PRINCIPLED, "sessions": (("Europe/Berlin", 9),)},
    "principled_cet_09_21": {**PRINCIPLED, "sessions": (("Europe/Berlin", 9), ("Europe/Berlin", 21))},
}


def run(name: str):
    tmp = os.environ["TEMP"]
    h1 = pickle.load(open(f"{tmp}/h1.pkl", "rb"))
    fees = pickle.load(open(f"{tmp}/fees.pkl", "rb"))
    funding = pickle.load(open(f"{tmp}/funding.pkl", "rb"))
    r = simulate(h1, fees, HumanPlan(**RUNS[name]), funding=funding, start="2023-03-01T00:00:00Z")
    return name, r


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "artifacts/human_sessions_regimes.pkl"
    with ProcessPoolExecutor(max_workers=6) as pool:
        results = dict(pool.map(run, list(RUNS)))
    pickle.dump(results, open(out, "wb"))
    print("done", len(results))
