import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import validation_harness_failure_resolution as resolution
from validation_pending_gate import unresolved_dispatches


class HarnessFailureResolutionTests(unittest.TestCase):
    def fixture(self):
        test = {'reason': 'exited', 'returncode': 1, 'reported_test_count': None,
                'output_sha256': 't' * 64}
        journal = {'schema': 1, 'phase': 'inspection_required', 'returncode': 1,
            'validation_vm_stopped': True, 'validation_passed': False,
            'manifest_sha256': 'm' * 64, 'sandbox_id': 'vm',
            'runner_summary': {'receipt': {'phase': 'complete',
                'test_command_succeeded': False, 'test': test}}}
        stdout = b'fixed harness failure output'
        raw = json.dumps(journal, sort_keys=True).encode()
        journal['stdout_sha256'] = hashlib.sha256(stdout).hexdigest()
        raw = json.dumps(journal, sort_keys=True).encode()
        return raw, stdout

    def patched(self, raw, stdout):
        return patch.multiple(resolution,
            DISPATCH_SHA256=hashlib.sha256(raw).hexdigest(),
            STDOUT_SHA256=hashlib.sha256(stdout).hexdigest(),
            TEST_OUTPUT_SHA256='t' * 64, MANIFEST_SHA256='m' * 64,
            UUID='vm', REPAIRS={'runner.py': 'r' * 64})

    def test_resolution_is_non_accepting_and_exact(self):
        raw, stdout = self.fixture()
        with self.patched(raw, stdout):
            value = resolution.build_resolution(raw, stdout, resolution.REPAIRS)
            for key in ('validation_passed', 'candidate_accepted', 'replay_permitted',
                        'model_start_authorized', 'source_feedback_delivered'):
                self.assertIs(value[key], False)
            self.assertTrue(value['replacement_validation_required'])
            resolution.verify_resolution(raw, stdout, resolution.canonical(value))
            with self.assertRaises(ValueError):
                resolution.verify_resolution(raw, stdout, resolution.canonical(dict(value, candidate_accepted=True)))

    def test_pending_gate_accepts_only_verified_resolution(self):
        raw, stdout = self.fixture()
        with tempfile.TemporaryDirectory() as temp, self.patched(raw, stdout):
            root = Path(temp).resolve()
            directory = root / ('dispatch-' + resolution.DISPATCH_ID)
            directory.mkdir(mode=0o700)
            (directory / 'dispatch.json').write_bytes(raw)
            (directory / 'stdout.log').write_bytes(stdout)
            value = resolution.build_resolution(raw, stdout, resolution.REPAIRS)
            (directory / 'harness-failure-resolution.json').write_bytes(resolution.canonical(value))
            vm = {'id': 'vm', 'status': 'stopped'}
            self.assertEqual(unresolved_dispatches(root, 'vm', vm), [])
            (directory / 'harness-failure-resolution.json').write_bytes(b'{}')
            self.assertEqual(len(unresolved_dispatches(root, 'vm', vm)), 1)


if __name__ == '__main__':
    unittest.main()
