import hashlib
import json
import unittest
from validation_dispatch_recovery import inspect_record
from test_sandbox_dispatch_receipt import fixture, DIGEST, IMAGE, BASE


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        envelope = fixture()
        envelope['receipt'].update(test_command_succeeded=True,
            test={'reason': 'exited', 'returncode': 0, 'reported_test_count': 273})
        self.output = json.dumps(envelope).encode()
        self.journal = {'schema': 1, 'phase': 'complete', 'sandbox_id': 'vm', 'manifest_sha256': DIGEST,
            'image_id': IMAGE, 'base': BASE, 'validation_passed': False, 'validation_vm_stopped': True,
            'returncode': 0, 'runner_summary': envelope, 'stdout_sha256': hashlib.sha256(self.output).hexdigest()}
        self.vm = {'id': 'vm', 'status': 'stopped'}

    def inspect(self, raw=None):
        return inspect_record(json.dumps(self.journal).encode() if raw is None else raw, self.output,
            digest=DIGEST, image=IMAGE, base=BASE, expected_vm='vm', live_vm=self.vm)

    def test_complete_is_not_acceptance_or_replay(self):
        result = self.inspect()
        self.assertEqual(result['outcome'], 'verified_completed_dispatch')
        self.assertFalse(result['validation_passed'])
        self.assertFalse(result['replay_permitted'])

    def test_incomplete_phases_always_require_inspection(self):
        for phase in ('prepared', 'running', 'result_received', 'cleanup_failed', 'inspection_required'):
            self.journal['phase'] = phase
            self.assertEqual(self.inspect()['outcome'], 'inspection_required')

    def test_live_identity_or_state_changes(self):
        for vm in ({'id': 'other', 'status': 'stopped'}, {'id': 'vm', 'status': 'running'}, None):
            self.vm = vm
            self.assertEqual(self.inspect()['outcome'], 'inspection_required')

    def test_output_tampering_or_missing(self):
        for output in (self.output + b' ', None):
            self.output = output
            self.assertEqual(self.inspect()['outcome'], 'inspection_required')

    def test_embedded_summary_tampering(self):
        self.journal['runner_summary']['receipt']['test']['reported_test_count'] = 999
        self.assertEqual(self.inspect()['outcome'], 'inspection_required')

    def test_terminal_claims(self):
        for key, value in [('validation_passed', True), ('validation_vm_stopped', False), ('returncode', True), ('image_id', 'other')]:
            old = self.journal[key]
            self.journal[key] = value
            self.assertEqual(self.inspect()['outcome'], 'inspection_required')
            self.journal[key] = old

    def test_malformed_json(self):
        for raw in (b'\xff', b'{"schema":1,"schema":1}', b'{"schema":NaN}', b'[]'):
            self.assertEqual(self.inspect(raw)['outcome'], 'inspection_required')

    def test_failed_empty_or_boolean_test_claim(self):
        for field, bad in [('reported_test_count', 0), ('reported_test_count', True), ('returncode', 1), ('reason', 'timeout')]:
            self.setUp()
            self.journal['runner_summary']['receipt']['test'][field] = bad
            self.output = json.dumps(self.journal['runner_summary']).encode()
            self.journal['stdout_sha256'] = hashlib.sha256(self.output).hexdigest()
            self.assertEqual(self.inspect()['outcome'], 'inspection_required')


if __name__ == '__main__':
    unittest.main()
