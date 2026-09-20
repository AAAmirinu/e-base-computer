import json
import hashlib
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from sandbox_feedback_delivery import deliver_feedback, verify_turn_feedback


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.feedback = {'capture_evidence': {'capture': {
            'role': 'stdlib', 'sandbox_id': 'vm', 'source_checkpoint': {}, 'manifest_sha256': 'a'*64}}}
        self.payload = (json.dumps(self.feedback, sort_keys=True, ensure_ascii=True,
                                   separators=(',', ':')) + '\n').encode()
        self.repo = Mock(controller=SimpleNamespace(sandbox_id='vm'))
        self.repo.path_kind.side_effect = lambda p: 'directory' if p == '.fleet' else 'missing'
        self.repo.read_bytes.return_value = self.payload
        self.capture = self.enterContext(patch('sandbox_feedback_delivery.capture_source_snapshot',
            return_value={'manifest_sha256': 'a'*64}))
        self.unchanged = self.enterContext(patch('sandbox_feedback_delivery._unchanged'))

    def test_copy_is_not_execution_or_acceptance(self):
        result = deliver_feedback(self.repo, self.feedback, self.payload)
        self.assertEqual(result['phase'], 'copied')
        self.assertFalse(result['model_executed'])
        self.assertFalse(result['hold_cleared'])
        self.repo.write_large_bytes.assert_called_once()
        self.unchanged.assert_called_once()

    def test_changed_full_manifest_refused_before_write(self):
        self.capture.return_value = {'manifest_sha256': 'b'*64}
        with self.assertRaises(ValueError):
            deliver_feedback(self.repo, self.feedback, self.payload)
        self.repo.write_large_bytes.assert_not_called()

    def test_wrong_vm(self):
        self.repo.controller.sandbox_id = 'other'
        with self.assertRaises(ValueError):
            deliver_feedback(self.repo, self.feedback, self.payload)
        self.capture.assert_not_called()

    def test_same_bytes_reconciled_without_overwrite(self):
        self.repo.path_kind.side_effect = lambda p: 'directory' if p == '.fleet' else 'regular'
        deliver_feedback(self.repo, self.feedback, self.payload)
        self.repo.write_large_bytes.assert_not_called()

    def test_conflicting_or_unsafe_target(self):
        for kind in ('regular', 'symlink', 'directory', 'hardlink'):
            self.repo.path_kind.side_effect = lambda p: 'directory' if p == '.fleet' else kind
            self.repo.read_bytes.return_value = b'conflict'
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                deliver_feedback(self.repo, self.feedback, self.payload)
        self.repo.write_large_bytes.assert_not_called()

    def test_readback_failure(self):
        self.repo.read_bytes.return_value = b'wrong'
        with self.assertRaises(RuntimeError):
            deliver_feedback(self.repo, self.feedback, self.payload)

    def test_required_existing_never_writes(self):
        with self.assertRaises(ValueError):
            deliver_feedback(self.repo, self.feedback, self.payload, require_existing=True)
        self.repo.write_large_bytes.assert_not_called()

    def turn_payload(self):
        self.repo.guest_root = '/home/agent/workspace/stdlib'
        self.feedback.update(schema=1, kind='failed_validation_feedback',
            validation_passed=False, replay_permitted=False, hold_cleared=False)
        payload = (json.dumps(self.feedback, sort_keys=True, separators=(',', ':'))+'\n').encode()
        self.repo.read_bytes.return_value = payload
        self.repo.path_kind.side_effect = lambda p: 'directory' if p == '.fleet' else 'regular'
        return payload, hashlib.sha256(payload).hexdigest()

    def test_turn_feedback_verified_without_write(self):
        payload, digest = self.turn_payload()
        self.assertEqual(verify_turn_feedback(self.repo, 'stdlib', payload, digest), digest)
        self.repo.write_large_bytes.assert_not_called()

    def test_turn_wrong_hash_or_role(self):
        payload, digest = self.turn_payload()
        for role, sha in [('kernel', digest), ('stdlib', '0'*64)]:
            with self.subTest(role=role), self.assertRaises(ValueError):
                verify_turn_feedback(self.repo, role, payload, sha)
        self.capture.assert_not_called()


if __name__ == '__main__':
    unittest.main()
