import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from validation_probe_closure import verify_closure
from validation_pending_gate import unresolved_dispatches


class ClosureTests(unittest.TestCase):
    def setUp(self):
        self.operation = 'a' * 32
        self.journal = {'schema': 1, 'phase': 'running', 'probe_kind': 'trusted_driver_sigkill',
            'source_executed': False, 'validation_passed': False, 'sandbox_id': 'vm', 'image_id': 'sha256:' + 'b' * 64}
        self.raw = json.dumps(self.journal).encode()
        self.crash = {'operation': self.operation, 'container_id': 'c' * 64,
            'journal_sha256': hashlib.sha256(self.raw).hexdigest(), 'source_executed': False,
            'guest_returncode': 137, 'container_survived_driver_crash': True,
            'container_running_after_vm_restart': False, 'restart_policy': 'no', 'vm_stopped': True, 'journal_unchanged': True}
        self.crash_raw = json.dumps(self.crash).encode()
        self.closure = {'schema': 1, 'action': 'abandon_synthetic_probe_no_replay', 'operation': self.operation,
            'sandbox_id': 'vm', 'journal_sha256': hashlib.sha256(self.raw).hexdigest(),
            'crash_sha256': hashlib.sha256(self.crash_raw).hexdigest(), 'container_id': 'c' * 64,
            'image_id': self.journal['image_id'], 'container_stopped': True, 'vm_stopped': True,
            'validation_passed': False, 'replay_permitted': False}
        self.vm = {'id': 'vm', 'status': 'stopped'}

    def verify(self):
        return verify_closure(self.raw, self.crash_raw, json.dumps(self.closure).encode(), self.operation, 'vm', self.vm)

    def test_valid_is_not_replay_or_acceptance(self):
        result = self.verify()
        self.assertFalse(result['replay_permitted'])
        self.assertFalse(result['validation_passed'])

    def test_each_closure_field_must_match(self):
        for field in self.closure:
            original = self.closure[field]
            self.closure[field] = None
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.verify()
            self.closure[field] = original

    def test_real_source_run_cannot_use_probe_closure(self):
        self.journal['source_executed'] = True
        self.raw = json.dumps(self.journal).encode()
        with self.assertRaises(ValueError):
            self.verify()

    def test_running_vm_refused(self):
        self.vm['status'] = 'running'
        with self.assertRaises(ValueError):
            self.verify()

    def test_modified_crash_evidence_refused(self):
        self.crash['container_running_after_vm_restart'] = True
        self.crash_raw = json.dumps(self.crash).encode()
        with self.assertRaises(ValueError):
            self.verify()

    def test_float_signal_code_refused(self):
        self.crash['guest_returncode'] = 137.0
        self.crash_raw = json.dumps(self.crash).encode()
        with self.assertRaises(ValueError):
            self.verify()

    def test_missing_image_refused(self):
        del self.journal['image_id']
        self.raw = json.dumps(self.journal).encode()
        with self.assertRaises(ValueError):
            self.verify()

    def test_gate_clears_only_bound_closure(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / ('dispatch-' + self.operation)
            directory.mkdir(mode=0o700)
            (directory / 'dispatch.json').write_bytes(self.raw)
            (directory / 'crash-evidence.json').write_bytes(self.crash_raw)
            self.assertEqual(len(unresolved_dispatches(root, 'vm', self.vm)), 1)
            (directory / 'closure.json').write_text(json.dumps(self.closure))
            self.assertEqual(unresolved_dispatches(root, 'vm', self.vm), [])
            self.assertEqual((directory / 'dispatch.json').read_bytes(), self.raw)
            self.closure['replay_permitted'] = True
            (directory / 'closure.json').write_text(json.dumps(self.closure))
            self.assertEqual(len(unresolved_dispatches(root, 'vm', self.vm)), 1)


if __name__ == '__main__':
    unittest.main()
