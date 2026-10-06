from pathlib import Path
import tempfile
import unittest

from orderflow_edge_lab.release_gates_v2 import complete_v2_suite


class V3ReleaseCoverageTests(unittest.TestCase):
    def test_failing_v3_cannot_hide_behind_passing_v2(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            tests = root / 'tests'
            tests.mkdir()
            (tests / '__init__.py').write_text('', encoding='utf-8')
            good = 'import unittest\nclass T(unittest.TestCase):\n def test_ok(self): pass\n'
            (tests / 'test_contracts_v2.py').write_text(good, encoding='utf-8')
            (tests / 'test_v2_control.py').write_text(good, encoding='utf-8')
            (tests / 'test_v3_hidden.py').write_text(
                "import unittest\nclass T(unittest.TestCase):\n def test_bad(self): self.fail('v3 must block release')\n", encoding='utf-8')
            passed, evidence = complete_v2_suite(root)
            self.assertFalse(passed)
            self.assertEqual(evidence['tests_run'], 3)
            self.assertIn('v3 must block release', evidence['output_tail'])
            self.assertIn('test_v3_*.py', evidence['discovery_pattern'])

    def test_v3_does_not_replace_foundational_requirement(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            tests = root / 'tests'
            tests.mkdir()
            (tests / '__init__.py').write_text('', encoding='utf-8')
            (tests / 'test_v3_control.py').write_text(
                'import unittest\nclass T(unittest.TestCase):\n def test_ok(self): pass\n', encoding='utf-8')
            passed, evidence = complete_v2_suite(root)
            self.assertFalse(passed)
            self.assertEqual(evidence['tests_run'], 1)
            self.assertFalse(evidence['foundational_contract_tests_present'])


if __name__ == '__main__':
    unittest.main()
