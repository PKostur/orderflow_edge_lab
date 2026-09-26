import json
import unittest
from collections import Counter
from pathlib import Path

from orderflow_edge_lab.descriptive_regime_labels_v1_1 import _null_centered_block_p

ROOT=Path(__file__).resolve().parents[1]

class Tests(unittest.TestCase):
    def test_v1_1_preserves_v1_label_contract(self):
        v1=json.loads((ROOT/"config/universal_descriptive_regime_labels_v1.json").read_text())
        v11=json.loads((ROOT/"config/universal_descriptive_regime_labels_v1_1.json").read_text())
        frozen=v11["frozen_v1_label_contract"]
        self.assertEqual(frozen["labels"],v1["labels"])
        self.assertEqual(frozen["attribution"],v1["attribution"])
        self.assertEqual(frozen["joint_cell_grid"],v1["joint_cell_grid"])
        self.assertEqual(frozen["primary_cost_bps"],v1["primary_cost_bps"])
        self.assertFalse(v11["claims"]["v1_label_definitions_changed"])
        self.assertFalse(v11["claims"]["regime_filter_authorized"])

    def test_null_centered_test_returns_one_when_observed_mean_is_zero(self):
        rows=[
            {"net_bps":100.0,"_block_id":0},
            {"net_bps":-100.0,"_block_id":1},
        ]
        samples=[
            Counter({0:1,1:1}),
            Counter({0:2}),
            Counter({1:2}),
        ]
        result=_null_centered_block_p(rows,samples)
        self.assertEqual(result["observed_expectancy_bps"],0.0)
        self.assertEqual(result["null_centered_two_sided_block_bootstrap_p"],1.0)
        self.assertEqual(result["valid_replicates"],3)

    def test_sparse_cells_are_blocked_by_frozen_eligibility_rule(self):
        cfg=json.loads((ROOT/"config/universal_descriptive_regime_labels_v1_1.json").read_text())
        self.assertGreater(cfg["inference"]["minimum_trades_for_hypothesis_test"],1)

    def test_minimum_cell_size_is_frozen_at_twenty(self):
        cfg=json.loads((ROOT/"config/universal_descriptive_regime_labels_v1_1.json").read_text())
        self.assertEqual(cfg["inference"]["minimum_trades_for_hypothesis_test"],20)
        self.assertTrue(cfg["inference"]["multiplicity"]["untested_sparse_cells_excluded_from_multiplicity_family"])

if __name__=="__main__":
    unittest.main()
