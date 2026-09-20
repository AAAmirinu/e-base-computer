import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid

import fleet
from sandbox_recovery import recover_sessions, RecoveryRejected


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.epoch = str(uuid.uuid4())
        self.registration = {'backend': 'sandbox', 'migration_epoch': self.epoch,
            'roles': {'machine': {'id': 'vm-id', 'name': 'e-base-machine'}}}
        self.raw = json.dumps({'session_id': 'current', 'steps': [
            {'source': 'agent', 'model_name': 'swe-2-high'}]}).encode()
        self.receipt = {'kind': 'sandbox', 'migration_epoch': self.epoch,
            'role': 'machine', 'sandbox_id': 'vm-id', 'sandbox_name': 'e-base-machine',
            'phase': 'export_verified', 'operation_id': uuid.uuid4().hex, 'sequence': 1,
            'session_id': 'current', 'export_sha256': hashlib.sha256(self.raw).hexdigest()}
        self.state = {'sessions': {'machine': 'legacy'}, 'candidates': {'preserved': {}}}

    def recover(self, records):
        return recover_sessions(self.state, self.registration, records)

    def test_verified_current_epoch_only_and_input_unchanged(self):
        result = self.recover([({}, b'legacy'), (self.receipt, self.raw)])
        self.assertEqual(result['sessions'], {'machine': 'current'})
        self.assertEqual(self.state['sessions'], {'machine': 'legacy'})
        self.assertEqual(result['candidates'], self.state['candidates'])

    def test_legacy_or_prepared_does_not_resurrect_session(self):
        self.receipt['phase'] = 'prepared'
        self.assertEqual(self.recover([({}, self.raw), (self.receipt, b'')])['sessions'], {})

    def test_identity_hash_model_mismatch_rejected(self):
        for field, value in [('sandbox_id', 'replacement'), ('export_sha256', 'bad'),
                             ('session_id', 'other'), ('sequence', True)]:
            with self.subTest(field=field), self.assertRaises(RecoveryRejected):
                self.recover([(dict(self.receipt, **{field: value}), self.raw)])
        raw = self.raw.replace(b'swe-2-high', b'other')
        with self.assertRaises(RecoveryRejected):
            self.recover([(dict(self.receipt, export_sha256=hashlib.sha256(raw).hexdigest()), raw)])

    def test_duplicate_receipt_rejected(self):
        with self.assertRaises(RecoveryRejected):
            self.recover([(self.receipt, self.raw)] * 2)

    def test_observed_display_label_recovers_identity_without_runtime_actions(self):
        raw = self.raw.replace(b'swe-2-high', b'SWE-2 High')
        receipt = dict(self.receipt, export_sha256=hashlib.sha256(raw).hexdigest())
        with patch('subprocess.run', side_effect=AssertionError('No runtime command')), \
                patch('subprocess.Popen', side_effect=AssertionError('No process start')):
            result = self.recover([(receipt, raw)])
        self.assertEqual(result['sessions'], {'machine': 'current'})
        self.assertEqual(self.state['sessions'], {'machine': 'legacy'})

    def test_export_names_share_live_execution_policy(self):
        for name in ('swe-2-high', 'SWE-2 High', 'swe-2-medium', 'SWE-2 Max',
                     'SWE-2 HIGH', 'swe-2-high ', 'Adaptive', 'other'):
            with self.subTest(name=name):
                export = {'session_id': 'current', 'steps': [
                    {'source': 'agent', 'model_name': name}]}
                raw = json.dumps(export).encode()
                receipt = dict(self.receipt, export_sha256=hashlib.sha256(raw).hexdigest())
                if name in ('swe-2-high', 'SWE-2 High'):
                    fleet.check_model(export)
                    self.assertEqual(self.recover([(receipt, raw)])['sessions'],
                                     {'machine': 'current'})
                else:
                    with self.assertRaises(RuntimeError):
                        fleet.check_model(export)
                    with self.assertRaises(RecoveryRejected):
                        self.recover([(receipt, raw)])

    def test_display_label_does_not_bypass_digest_or_prepared_gate(self):
        raw = self.raw.replace(b'swe-2-high', b'SWE-2 High')
        with self.assertRaises(RecoveryRejected):
            self.recover([(self.receipt, raw)])
        receipt = dict(self.receipt, phase='prepared',
                       export_sha256=hashlib.sha256(raw).hexdigest())
        self.assertEqual(self.recover([(receipt, raw)])['sessions'], {})

    def test_marked_root_never_reaches_host_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'execution.json').write_text('malformed marker')
            (root / 'STOP').write_bytes(b'keep')
            calls = [lambda: fleet.prepare(root, resume=True), lambda: fleet.loop(root, 1),
                lambda: fleet.configure(root), lambda: fleet.recover_finished(root, self.state),
                lambda: fleet.recover_integration(root, self.state),
                lambda: fleet.reconcile_integration(root, self.state)]
            with patch.object(fleet, 'run', side_effect=AssertionError('host run')), \
                    patch.object(fleet, 'load_state', side_effect=AssertionError('state load')):
                for call in calls:
                    with self.assertRaisesRegex(RuntimeError, 'legacy host'):
                        call()
            self.assertEqual((root / 'STOP').read_bytes(), b'keep')


if __name__ == '__main__':
    unittest.main()
