"""Regressions for hosted-runner contamination and YAML heredoc execution."""
from __future__ import annotations

from pathlib import Path
import json
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]


def literal_run_blocks(text: str) -> list[tuple[str, str]]:
    lines = text.splitlines(keepends=True)
    blocks: list[tuple[str, str]] = []
    name = ''
    for index, line in enumerate(lines):
        if line.startswith('      - name: '):
            name = line.strip().removeprefix('- name: ')
        if not line.startswith('        run: |'):
            continue
        body = []
        for following in lines[index + 1:]:
            indentation = len(following) - len(following.lstrip(' '))
            if following.strip() and indentation <= 8:
                break
            body.append(following)
        blocks.append((name, textwrap.dedent(''.join(body))))
    return blocks


class WorkflowExecutionRegressionTests(unittest.TestCase):
    def bash(self) -> str:
        git_bash = Path('C:/Program Files/Git/bin/bash.exe')
        executable = str(git_bash) if git_bash.exists() else shutil.which('bash')
        if executable is None:
            self.skipTest('bash unavailable for shell syntax checks')
        return executable

    def test_digest_literal_shell_blocks_have_no_syntax_errors_or_heredoc_warnings(self) -> None:
        blocks = literal_run_blocks((ROOT / '.github/workflows/wait-window-ops-digest-v1.yml').read_text())
        self.assertGreater(len(blocks), 5)
        for name, script in blocks:
            with self.subTest(step=name):
                result = subprocess.run([self.bash(), '-n'], input=script.encode('utf-8'), capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, b'', result.stderr)

    def test_unclosed_heredoc_is_a_warning_even_when_bash_returns_zero(self) -> None:
        result = subprocess.run([self.bash(), '-n'], input=b"python - <<'PY'\nprint('fixture')\n", capture_output=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn(b'here-document', result.stderr)

    def run_inventory_fixture(self, payload: object) -> tuple[dict, list[dict]]:
        blocks = dict(literal_run_blocks((ROOT / '.github/workflows/wait-window-ops-digest-v1.yml').read_text()))
        script = blocks['Inventory retained CI artifacts with explicit acquisition outcome']
        script, replacements = re.subn(
            r'gh api .*?2> artifacts/inventory_acquisition.stderr\n',
            'printf \'%s\\n\' "$FIXTURE_PAGES" > artifacts/artifact_inventory.pages.json 2> artifacts/inventory_acquisition.stderr\n',
            script, count=1, flags=re.S)
        self.assertEqual(replacements, 1)
        with tempfile.TemporaryDirectory() as temp:
            result = subprocess.run([self.bash()], input=script.encode('utf-8'), cwd=temp,
                                    env=dict(os.environ, FIXTURE_PAGES=json.dumps(payload)), capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            artifact = Path(temp) / 'artifacts'
            outcome = json.loads((artifact / 'inventory_acquisition.json').read_text())
            items = [json.loads(line) for line in (artifact / 'artifact_inventory.jsonl').read_text().splitlines()]
        return outcome, items

    def test_inventory_records_actual_two_page_response_without_network(self) -> None:
        outcome, items = self.run_inventory_fixture([
            {'artifacts': [{'name': 'first', 'id': 1}]},
            {'artifacts': [{'name': 'second', 'id': 2}]},
        ])
        self.assertEqual(outcome['status'], 'ACQUIRED')
        self.assertEqual(outcome['pages_fetched'], 2)
        self.assertEqual([item['id'] for item in items], [1, 2])

    def test_invalid_inventory_is_failed_not_complete_empty_inventory(self) -> None:
        outcome, items = self.run_inventory_fixture({'message': 'not artifact pages'})
        self.assertEqual(outcome['status'], 'FAILED')
        self.assertEqual(outcome['pages_fetched'], 0)
        self.assertEqual(items, [])
        self.assertIn('invalid inventory response', outcome['error'])

    def test_ci_checkout_tests_are_isolated_before_dependency_installation(self) -> None:
        text = (ROOT / '.github/workflows/ci.yml').read_text()
        self.assertLess(text.index('python -m venv .venv-ci'), text.index('Install reviewed hash-locked'))
        self.assertIn("os.environ['GITHUB_PATH']", text)
        self.assertIn("'Scripts' if os.name=='nt' else 'bin'", text)
        self.assertLess(text.index('core.autocrlf false'), text.index('actions/checkout@'))
        self.assertNotIn('pip uninstall pipx', text)


if __name__ == '__main__':
    unittest.main()
