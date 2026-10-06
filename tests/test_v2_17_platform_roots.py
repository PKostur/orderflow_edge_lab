"""Release-gate caller roots are canonicalized before descendant checks."""
from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock

from orderflow_edge_lab.governance_v2 import load_policy_config
from orderflow_edge_lab.release_gates_v2 import (
    complete_v2_suite, generated_map_parity, isolated_install_console_smoke,
)

ROOT = Path(__file__).resolve().parents[1]


class PlatformRootRegressionTests(unittest.TestCase):
    def test_alias_root_is_resolved_before_map_suite_and_install_safety_checks(self) -> None:
        config = load_policy_config(ROOT / 'config/multi_agents_v2.json')
        with tempfile.TemporaryDirectory() as temp:
            canonical = Path(temp).resolve()
            for name in ('config/multi_agents_v2.json', 'docs/governance_map_v2.json', 'docs/GOVERNANCE_MAP_V2.md'):
                target = canonical / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / name, target)
            (canonical / 'tests').mkdir()
            (canonical / 'tests/__init__.py').write_text('', encoding='utf-8')
            test = 'import unittest\nclass T(unittest.TestCase):\n def test_ok(self): pass\n'
            (canonical / 'tests/test_v2_fixture.py').write_text(test, encoding='utf-8')
            (canonical / 'tests/test_contracts_v2.py').write_text(test, encoding='utf-8')
            # Windows TEMP can use RUNNER~1 while resolve() returns its long
            # name. Model the canonicalization contract without OS privileges.
            for gate in ('map', 'suite', 'install'):
                with self.subTest(gate=gate):
                    caller_root = MagicMock(spec=Path)
                    caller_root.resolve.return_value = canonical
                    caller_root.__truediv__.side_effect = AssertionError('canonicalize the caller root first')
                    if gate == 'map':
                        passed, evidence = generated_map_parity(caller_root, config)
                        self.assertTrue(passed, evidence)
                    elif gate == 'suite':
                        passed, evidence = complete_v2_suite(caller_root)
                        self.assertTrue(passed, evidence)
                        self.assertEqual(evidence['tests_run'], 2)
                    else:
                        passed, evidence = isolated_install_console_smoke(caller_root)
                        self.assertFalse(passed)
                        self.assertEqual(evidence['error'], 'packaging_inputs_missing_or_unsafe')
                    caller_root.resolve.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
