"""Engineering publication must not collect new observations or bootstrap tools."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
GUARD = "    if: ${{ github.event_name != 'pull_request' || !startsWith(github.head_ref, 'improvement/process-integrity-v2-') }}\n"
COMMENTS = (
    "    # Engineering-only successor PRs must not create research observations.\n",
    "    # Engineering-only successor PRs do not bootstrap optional orchestrators.\n",
)


class EngineeringPublicationBoundaryTests(unittest.TestCase):
    def test_guarded_workflows_preserve_original_bytes_except_declared_operational_changes(self) -> None:
        manifest = json.loads((ROOT / 'tests/fixtures/v2_15_workflow_boundaries.json').read_text())
        self.assertEqual(len(manifest), 9)
        for row in manifest:
            with self.subTest(workflow=row['path']):
                text = (ROOT / row['path']).read_text()
                self.assertEqual(text.count(GUARD), 1)
                self.assertLess(text.index(GUARD), text.index('    runs-on:'))
                restored = text.replace(GUARD, '')
                for comment in COMMENTS:
                    restored = restored.replace(comment, '')
                if row['path'].endswith('high-cadence-evidence-capture-v1.yml'):
                    restored = restored.replace('          retention-days: 14\n          if-no-files-found: error',
                                                '          retention-days: 7\n          if-no-files-found: error')
                self.assertEqual(hashlib.sha256(restored.encode()).hexdigest(), row['baseline_sha256'])

    def test_guard_truth_table_preserves_schedule_manual_and_other_research_prs(self) -> None:
        # This is the exact documented boolean expression in all nine jobs.
        cases = [('pull_request', 'improvement/process-integrity-v2-20261006', False),
                 ('pull_request', 'research/independent-study', True),
                 ('schedule', '', True), ('workflow_dispatch', '', True),
                 ('push', 'improvement/process-integrity-v2-20261006', True)]
        for event, head, expected in cases:
            with self.subTest(event=event, head=head):
                observed = event != 'pull_request' or not head.startswith('improvement/process-integrity-v2-')
                self.assertEqual(observed, expected)


if __name__ == '__main__':
    unittest.main()
