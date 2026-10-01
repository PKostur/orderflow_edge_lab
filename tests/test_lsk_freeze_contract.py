import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from orderflow_edge_lab.lsk_conditional_regime import main, code_digest


class FreezeContractTests(unittest.TestCase):
    def invoke(self,*args):
        with patch.object(sys,'argv',['lsk',*map(str,args)]),contextlib.redirect_stdout(io.StringIO()): main()

    def test_freeze_exclusive_and_preboundary_rejected_before_evaluation(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); freeze=root/'freeze.json'; output=root/'result.json'
            self.invoke('--create-freeze','--freeze',freeze,'--output',output)
            with self.assertRaises(FileExistsError): self.invoke('--create-freeze','--freeze',freeze,'--output',output)
            old=root/'old.jsonl'; old.write_text(json.dumps(dict(received_at_ns=1))+'\n')
            with patch('orderflow_edge_lab.lsk_conditional_regime.evaluate_capture') as evaluator:
                with self.assertRaisesRegex(ValueError,'pre-freeze'): self.invoke(old,'--mode','forward','--freeze',freeze,'--output',output)
                evaluator.assert_not_called()

    def test_tampered_identity_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); freeze=root/'freeze.json'; output=root/'result.json'
            self.invoke('--create-freeze','--freeze',freeze,'--output',output)
            payload=json.loads(freeze.read_text()); payload['dependency_sha256']='0'*64; freeze.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError,'identity mismatch'): self.invoke('--freeze',freeze,'--output',output)

    def test_code_hash_survives_platform_newlines(self):
        with tempfile.TemporaryDirectory() as d:
            a=Path(d)/'a'; b=Path(d)/'b'; a.write_bytes(b'a\nb\n'); b.write_bytes(b'a\r\nb\r\n')
            self.assertEqual(code_digest(a),code_digest(b))


if __name__=='__main__': unittest.main()
