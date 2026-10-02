import json
import unittest
from pathlib import Path

import numpy as np

from orderflow_edge_lab.descriptive_regime_marginal_pairwise_v1 import (
    _bh,
    _bootstrap_weights,
    _by,
    _contrast_bootstrap,
    _holm,
    all_specs,
    marginal_specs,
    pairwise_specs,
)

ROOT = Path(__file__).resolve().parents[1]


class Tests(unittest.TestCase):
    def test_fixed_symmetric_contrast_family(self):
        self.assertEqual(len(marginal_specs()), 14)
        self.assertEqual(len(pairwise_specs()), 78)
        specs = all_specs()
        self.assertEqual(len(specs), 92)
        ids = [row["contrast_id"] for row in specs]
        self.assertEqual(len(ids), len(set(ids)))

    def test_protocol_forbids_result_selected_pairs(self):
        cfg = json.loads(
            (ROOT / "config/universal_descriptive_regime_marginal_pairwise_v1.json")
            .read_text(encoding="utf-8")
        )
        hierarchy = cfg["hierarchy"]
        self.assertTrue(hierarchy["all_marginal_parent_states_are_always_emitted"])
        self.assertTrue(hierarchy["all_unordered_axis_pairs_are_secondary"])
        self.assertTrue(hierarchy["all_pairwise_state_combinations_are_always_emitted"])
        self.assertTrue(hierarchy["pair_selection_from_historical_pnl_prohibited"])
        self.assertTrue(hierarchy["state_selection_from_historical_pnl_prohibited"])
        self.assertEqual(hierarchy["expected_total_contrasts_per_strategy"], 92)
        self.assertFalse(cfg["claims"]["historical_pnl_selected_pairs"])
        self.assertFalse(cfg["claims"]["regime_filter_authorized"])

    def test_null_centered_contrast_returns_p_one_for_zero_observed_difference(self):
        pool = [
            {"net_bps": 100.0, "_block_index": 0},
            {"net_bps": -100.0, "_block_index": 1},
            {"net_bps": 100.0, "_block_index": 0},
            {"net_bps": -100.0, "_block_index": 1},
        ]
        flags = np.asarray([True, True, False, False], dtype=bool)
        weights = _bootstrap_weights(2, 100, 123)
        result = _contrast_bootstrap(
            pool,
            flags,
            weights,
            block_count=2,
            confidence_interval=(0.025, 0.975),
        )
        self.assertEqual(result["observed_difference_bps"], 0.0)
        self.assertEqual(
            result["null_centered_two_sided_block_bootstrap_p"],
            1.0,
        )
        self.assertGreater(result["valid_replicates"], 0)

    def test_by_is_not_less_conservative_than_bh_and_holm_not_below_raw_p(self):
        values = [0.001, 0.01, 0.04, 0.2, 0.6]
        bh = _bh(values)
        by = _by(values)
        holm = _holm(values)
        for raw, q_bh, q_by, p_holm in zip(values, bh, by, holm):
            self.assertGreaterEqual(q_by + 1e-15, q_bh)
            self.assertGreaterEqual(p_holm + 1e-15, raw)

    def test_inference_breadth_floor_is_preregistered(self):
        cfg = json.loads(
            (ROOT / "config/universal_descriptive_regime_marginal_pairwise_v1.json")
            .read_text(encoding="utf-8")
        )
        eligibility = cfg["eligibility"]
        self.assertEqual(eligibility["minimum_group_trades"], 20)
        self.assertEqual(eligibility["minimum_group_symbols"], 3)
        self.assertEqual(eligibility["minimum_group_blocks"], 3)
        self.assertEqual(eligibility["minimum_valid_bootstrap_replicates"], 1000)
        self.assertEqual(cfg["multiplicity"]["primary_conservative_reference"], "global Holm FWER")


if __name__ == "__main__":
    unittest.main()
