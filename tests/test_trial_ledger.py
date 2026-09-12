from __future__ import annotations

from datetime import datetime, timezone
import copy
import hashlib
import json
import unittest

from orderflow_edge_lab.trial_ledger import (
    TrialLedgerError,
    append_holdout_trial,
    new_trial_ledger,
    verify_trial_ledger,
)

UTC = timezone.utc


def canonical_sha(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def fake_holdout(candidate_id="c1", marker="a"):
    digest = hashlib.sha256(marker.encode()).hexdigest()
    manifest = {
        "schema_version": 1,
        "created_at": "2026-09-12T00:00:00+00:00",
        "candidate_id": candidate_id,
        "candidate_spec_sha256": digest,
        "candidate_freeze": {
            "path": "candidate.json",
            "manifest_sha256": hashlib.sha256((marker + "freeze").encode()).hexdigest(),
            "registry_sha256": hashlib.sha256((marker + "registry").encode()).hexdigest(),
        },
        "partition": {
            "holdout_start_exclusive": "2026-09-01T00:00:00+00:00",
            "holdout_end": "2026-09-10T00:00:00+00:00",
        },
        "observations": {
            "path": "obs.jsonl",
            "sha256": hashlib.sha256((marker + "obs").encode()).hexdigest(),
            "total_rows": 10,
            "candidate_rows": 10,
            "earliest_event": "2026-09-02T00:00:00+00:00",
            "latest_event": "2026-09-09T00:00:00+00:00",
            "latest_outcome": "2026-09-09T01:00:00+00:00",
            "dataset_sha256": [hashlib.sha256((marker + "data").encode()).hexdigest()],
        },
        "source_reverification": {"performed": True, "files": []},
        "claims": {
            "candidate_specification_frozen": True,
            "holdout_partition_respected": True,
            "source_bytes_reverified": True,
            "verified_out_of_sample_evidence": False,
            "profitable_edge_established": False,
            "live_order_transmission_supported": False,
        },
    }
    manifest["manifest_sha256"] = canonical_sha(manifest)
    return manifest


class TrialLedgerTests(unittest.TestCase):
    def test_counts_trials_and_adjusts_alpha(self):
        ledger = new_trial_ledger(family_name="nq-ofi-v1", alpha=0.05, now=datetime(2026, 9, 12, tzinfo=UTC))
        ledger = append_holdout_trial(ledger, fake_holdout("c1", "a"), now=datetime(2026, 9, 12, 1, tzinfo=UTC))
        self.assertTrue(verify_trial_ledger(ledger))
        self.assertEqual(len(ledger["trials"]), 1)
        self.assertAlmostEqual(ledger["trials"][0]["bonferroni_alpha"], 0.05)
        ledger = append_holdout_trial(ledger, fake_holdout("c2", "b"), now=datetime(2026, 9, 12, 2, tzinfo=UTC))
        self.assertTrue(verify_trial_ledger(ledger))
        self.assertAlmostEqual(ledger["trials"][1]["bonferroni_alpha"], 0.025)

    def test_duplicate_holdout_inspection_is_rejected(self):
        ledger = new_trial_ledger(family_name="family")
        audit = fake_holdout()
        ledger = append_holdout_trial(ledger, audit)
        with self.assertRaisesRegex(TrialLedgerError, "already counted"):
            append_holdout_trial(ledger, audit)

    def test_tampered_ledger_fails_verification(self):
        ledger = append_holdout_trial(new_trial_ledger(family_name="family"), fake_holdout())
        tampered = copy.deepcopy(ledger)
        tampered["family_alpha"] = 0.5
        self.assertFalse(verify_trial_ledger(tampered))

    def test_tampered_holdout_is_rejected(self):
        audit = fake_holdout()
        audit["candidate_id"] = "changed"
        with self.assertRaisesRegex(TrialLedgerError, "holdout audit is invalid"):
            append_holdout_trial(new_trial_ledger(family_name="family"), audit)


if __name__ == "__main__":
    unittest.main()
