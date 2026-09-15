from __future__ import annotations

import hashlib

import run_gold_macro_event_reaction_v1 as base


_original_evaluate_cell = base.evaluate_cell


def _stable_seed(base_seed: int, candidate_id: str) -> int:
    digest = hashlib.sha256(candidate_id.encode("utf-8")).digest()
    offset = int.from_bytes(digest[:4], "big")
    return int((int(base_seed) + offset) % (2**32 - 1))


def _deterministic_evaluate_cell(d, events, event_type, mode, hold, start_ts, cfg):
    out = _original_evaluate_cell(d, events, event_type, mode, hold, start_ts, cfg)
    fold_metrics = out.get("state_fold_metrics", [])
    fold_excess = [float(x["mean_state_excess_bps"]) for x in fold_metrics]
    out["state_sign_flip_p"] = base.sign_flip_pvalue(
        fold_excess,
        int(cfg["state_first"]["fold_mean_sign_flip_epochs"]),
        _stable_seed(
            int(cfg["state_first"]["fold_mean_sign_flip_seed"]),
            str(out["candidate_id"]),
        ),
    )
    out["permutation_seed_method"] = "sha256(candidate_id)"
    return out


base.evaluate_cell = _deterministic_evaluate_cell


if __name__ == "__main__":
    base.main()
