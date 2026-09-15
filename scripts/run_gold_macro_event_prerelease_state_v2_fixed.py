from __future__ import annotations

import numpy as np
import pandas as pd

import run_gold_macro_event_prerelease_state_v2 as base


def _fixed_permutation_p(g, predictor, target, observed, cfg, hid):
    """Mechanical repair: convert filtered rows to contiguous positional indices before numpy shuffles."""
    pc = cfg["state_first"]["permutation_control"]
    epochs = int(pc["epochs"])
    rng = np.random.default_rng(base.stable_seed(int(pc["seed"]), hid))

    # The only semantic difference from the frozen implementation is this
    # reset_index: groupby indices are now valid positions into the numpy arrays.
    base_frame = g[["event_time", predictor, target]].dropna().reset_index(drop=True).copy()
    base_frame["year"] = base_frame["event_time"].dt.year
    groups = [idx.to_numpy() for _, idx in base_frame.groupby("year").groups.items()]

    start = pd.Timestamp(cfg["periods"]["development"]["start"])
    cluster = int(cfg["state_first"]["dependence_cluster_calendar_days"])
    minimum = int(cfg["state_first"]["minimum_events_per_scorable_fold"])
    base_frame["fold"] = np.floor(
        (base_frame["event_time"] - start) / pd.Timedelta(days=cluster)
    ).astype(int)

    pvals = base_frame[predictor].to_numpy(float)
    targets = base_frame[target].to_numpy(float)
    folds = base_frame["fold"].to_numpy(int)

    count = 0
    scored = 0
    for _ in range(epochs):
        pp = pvals.copy()
        for idx in groups:
            pp[idx] = pp[rng.permutation(idx)]
        rs = []
        for fid in np.unique(folds):
            mask = folds == fid
            if int(mask.sum()) < minimum:
                continue
            r = base.rho(pp[mask], targets[mask])
            if np.isfinite(r):
                rs.append(r)
        if rs:
            null = float(np.median(rs))
            scored += 1
            if null >= observed:
                count += 1
    return float((count + 1) / (scored + 1)) if scored else float("nan")


base.permutation_p = _fixed_permutation_p


if __name__ == "__main__":
    base.main()
