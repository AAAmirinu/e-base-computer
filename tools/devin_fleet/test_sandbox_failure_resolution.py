import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import test_sandbox_failure_feedback as feedback_tests
from validation_failure_resolution import build_resolution, verify_resolution, canonical
from validation_pending_gate import unresolved_dispatches


class ResolutionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = feedback_tests.FeedbackTests()
        self.fixture.setUp()
        self.feedback = canonical(self.fixture.build())
        self.raw = json.dumps(self.fixture.journal).encode()
        self.output = json.dumps(self.fixture.summary).encode()
        digest = hashlib.sha256(self.feedback).hexdigest()
        self.delivery = {'schema': 1, 'phase': 'delivered', 'role': 'stdlib', 'sandbox_id': 'role-vm',
            'manifest_sha256': 'a'*64, 'feedback_sha256': digest,
            'guest_path': '.fleet/validation-feedback-'+digest+'.json',
            'source_vm_stopped': True, 'source_freshness_verified': True,
            'validation_passed': False, 'model_executed': False, 'hold_cleared': False}
        self.dispatch = 'f'*32

    def build(self):
        return build_resolution(self.raw, self.output, self.feedback, canonical(self.delivery),
            dispatch_id=self.dispatch, capture_evidence=self.fixture.capture,
            expected_vm='vm', live_vm=self.fixture.vm)

    def test_rejection_is_not_acceptance(self):
        result = self.build()
        self.assertEqual(result['outcome'], 'rejected_awaiting_repair')
        self.assertNotEqual(result['dispatch_id'], result['operation'])
        for key in ('validation_passed', 'replay_permitted', 'candidate_accepted', 'model_start_authorized'):
            self.assertIs(result[key], False)

    def test_wrong_delivery_claims(self):
        for key, value in [('schema', True), ('phase', 'prepared'), ('role', 'kernel'),
                           ('sandbox_id', 'other'), ('manifest_sha256', 'b'*64),
                           ('source_vm_stopped', False), ('source_freshness_verified', False),
                           ('model_executed', True), ('guest_path', '.fleet/other')]:
            self.setUp()
            self.delivery[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.build()

    def test_modified_original_evidence_refused(self):
        for field in ('raw', 'output', 'feedback'):
            self.setUp()
            resolution = canonical(self.build())
            setattr(self, field, getattr(self, field)+b' ')
            with self.subTest(field=field), self.assertRaises(ValueError):
                verify_resolution(self.raw, self.output, self.feedback, canonical(self.delivery),
                    resolution, self.dispatch, 'vm', self.fixture.vm)

    def test_historical_gate_and_conflicts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            directory = root/('dispatch-'+self.dispatch)
            directory.mkdir(mode=0o700)
            records = {'dispatch.json': self.raw, 'stdout.log': self.output,
                'failure-feedback.json': self.feedback, 'feedback-delivery.json': canonical(self.delivery),
                'failure-resolution.json': canonical(self.build())}
            for name, raw in records.items():
                (directory/name).write_bytes(raw)
            self.assertEqual(unresolved_dispatches(root, 'vm', self.fixture.vm), [])
            self.assertEqual((directory/'dispatch.json').read_bytes(), self.raw)
            (directory/'closure.json').write_bytes(b'{}')
            self.assertEqual(len(unresolved_dispatches(root, 'vm', self.fixture.vm)), 1)

    def test_partial_resolution_refused(self):
        with self.assertRaises(ValueError):
            verify_resolution(self.raw, self.output, self.feedback, canonical(self.delivery),
                b'{', self.dispatch, 'vm', self.fixture.vm)

    def test_foreign_outer_identity_refused(self):
        with self.assertRaises(ValueError):
            verify_resolution(self.raw, self.output, self.feedback, canonical(self.delivery),
                canonical(self.build()), '0'*32, 'vm', self.fixture.vm)


if __name__ == '__main__':
    unittest.main()
