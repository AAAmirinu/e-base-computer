import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import fleet
from sandbox_repository import GuestRepository


class TurnTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.entry = {'paths': ['src/**']}
        self.state = {'round': 7, 'reports': {}, 'candidates': {}, 'sessions': {'machine': 'legacy'}}
        self.repo = GuestRepository(Mock(), '/home/agent/workspace/machine', self.root)
        self.repo.git = Mock(return_value='a.py\0line\nb.py\0')
        self.repo.write_bytes = Mock()

    def prepare(self, role='machine', **kwargs):
        return fleet.prepare_guest_turn(self.root, self.repo, role, self.entry, self.state, **kwargs)

    def test_guest_prompt_matches_file_only_policy_and_keeps_legacy_separate(self):
        entry = dict(self.entry, title='machine', mission='improve emulator', first_task='bounded fix')
        with patch.object(Path, 'read_text', return_value='Trusted charter'):
            guest = fleet.prompt(self.root, 'machine', entry, self.state, guest=True)
            legacy = fleet.prompt(self.root, 'machine', entry, self.state)
        self.assertIn('All shell/Exec tools are denied', guest)
        self.assertIn('separate credential-free validator', guest)
        self.assertNotIn('shell discovery', guest)
        self.assertIn('shell discovery', legacy)

    def test_guest_preparation_selects_guest_prompt(self):
        with patch.object(fleet, 'read', return_value={'machine': self.entry}), \
                patch.object(fleet, 'sha', return_value='a' * 40), \
                patch.object(fleet, 'prompt', return_value='mission') as prompt, \
                patch.object(fleet, 'stage_guest_model_inputs', return_value={'args': []}):
            self.prepare()
        prompt.assert_called_once_with(self.root, 'machine', self.entry, self.state, guest=True)

    def test_context_staging_connected_without_legacy_session(self):
        with patch.object(fleet, 'read', return_value={'machine': self.entry}), \
                patch.object(fleet, 'sha', return_value='a' * 40), \
                patch.object(fleet, 'prompt', return_value='Read .fleet/context.json and .fleet/files.txt'), \
                patch.object(fleet, 'stage_guest_model_inputs', return_value={'args': []}) as stage:
            result = self.prepare()
        self.assertEqual(result['base'], 'a' * 40)
        self.assertEqual(result['round'], 7)
        args = stage.call_args.args
        self.assertIsNone(args[3])
        self.assertIn('{FLEET_INPUTS}/context.json', args[2])
        self.assertEqual(json.loads(args[4]['files.txt']), ['a.py', 'line\nb.py'])
        self.assertEqual(self.repo.write_bytes.call_count, 2)

    def test_role_mismatch_never_stages(self):
        with patch.object(fleet, 'read', return_value={'kernel': self.entry}), self.assertRaises(ValueError):
            self.prepare('kernel')
        self.repo.git.assert_not_called()

    def test_missing_coordinator_evidence_rejected(self):
        self.repo.guest_root = '/home/agent/workspace/coordinator'
        self.state['candidates'] = {'b' * 40: {'status': 'pending'}}
        with patch.object(fleet, 'read', return_value={'coordinator': self.entry}), \
                patch.object(fleet, 'sha', return_value='a' * 40), \
                patch.object(fleet, 'prompt', return_value='Read .fleet/candidates/'), self.assertRaises(ValueError):
            self.prepare('coordinator')
        self.repo.write_bytes.assert_not_called()

    def test_verified_feedback_in_fixed_inputs_and_prompt(self):
        with patch.object(fleet, 'read', return_value={'machine': self.entry}), \
                patch.object(fleet, 'sha', return_value='a'*40), \
                patch.object(fleet, 'prompt', return_value='mission'), \
                patch('sandbox_feedback_delivery.verify_turn_feedback') as verify, \
                patch.object(fleet, 'stage_guest_model_inputs', return_value={'args': []}) as stage:
            result = self.prepare(validation_feedback=b'evidence', validation_feedback_sha256='f'*64)
        verify.assert_called_once_with(self.repo, 'machine', b'evidence', 'f'*64)
        self.assertEqual(stage.call_args.args[4]['validation-feedback.json'], b'evidence')
        self.assertIn('f'*64, stage.call_args.args[2])
        self.assertIn('untrusted evidence', stage.call_args.args[2])
        self.assertEqual(result['validation_feedback_sha256'], 'f'*64)

    def test_rejected_feedback_never_stages(self):
        with patch.object(fleet, 'read', return_value={'machine': self.entry}), \
                patch.object(fleet, 'sha', return_value='a'*40), \
                patch.object(fleet, 'prompt', return_value='mission'), \
                patch('sandbox_feedback_delivery.verify_turn_feedback', side_effect=ValueError('stale')), \
                patch.object(fleet, 'stage_guest_model_inputs') as stage:
            with self.assertRaises(ValueError):
                self.prepare(validation_feedback=b'evidence', validation_feedback_sha256='f'*64)
        stage.assert_not_called()
        self.repo.write_bytes.assert_not_called()


if __name__ == '__main__':
    unittest.main()
