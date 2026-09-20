import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

import fleet
from sandbox_repository import GuestRepository


class InputTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.controller = Mock()
        self.repo = GuestRepository(self.controller, '/home/agent/workspace/machine', Path(self.tmp.name))
        self.files = {}
        self.repo.make_directory = Mock()
        self.repo.write_bytes = Mock(side_effect=self.files.__setitem__)
        self.repo.sha256 = Mock(side_effect=lambda p: hashlib.sha256(self.files[p]).hexdigest())

    def test_guest_scopes_and_exact_input_hashes(self):
        result = fleet.stage_guest_model_inputs(self.repo, {'paths': ['src/**']}, 'hello', 'existing')
        config = json.loads(self.files[result['relative'] + '/config.json'])
        self.assertEqual(result['args'][0], '/home/agent/.local/bin/devin-cli')
        self.assertEqual(config['agent']['model'], 'swe-2-high')
        self.assertIn('Write(/home/agent/workspace/machine/src/**)', config['permissions']['allow'])
        self.assertIn('Write(/home/agent/workspace/machine/.fleet/control-*/**)', config['permissions']['deny'])
        self.assertEqual(result['args'][-2:], ['--resume', 'existing'])
        self.assertEqual(result['config_sha256'], self.repo.sha256(result['relative'] + '/config.json'))
        self.assertFalse(any(p.endswith('export.json') for p in self.files))

    def test_fresh_directory_per_attempt(self):
        one = fleet.stage_guest_model_inputs(self.repo, {'paths': ['src/**']}, 'one')
        two = fleet.stage_guest_model_inputs(self.repo, {'paths': ['src/**']}, 'two')
        self.assertNotEqual(one['relative'], two['relative'])

    def test_guest_model_shell_is_denied_without_changing_legacy_policy(self):
        entry = {'paths': ['src/**']}
        legacy_before = fleet.permission_config(self.repo.guest_root, entry)
        result = fleet.stage_guest_model_inputs(self.repo, entry, 'file tools only')
        config = json.loads(self.files[result['relative'] + '/config.json'])
        self.assertIn('exec', config['permissions']['deny'])
        self.assertIn('Exec(*)', config['permissions']['deny'])
        self.assertFalse(any(rule.startswith('Exec(') for rule in config['permissions']['allow']))
        self.assertIn('Read(/home/agent/workspace/machine/**)', config['permissions']['allow'])
        self.assertIn('Write(/home/agent/workspace/machine/src/**)', config['permissions']['allow'])
        self.assertIn('Read(**/*credentials*)', config['permissions']['deny'])
        self.assertIn('Read(**/.env*)', config['permissions']['deny'])
        self.assertEqual(fleet.permission_config(self.repo.guest_root, entry), legacy_before)
        self.assertIn('Exec(cat)', legacy_before['permissions']['allow'])

    def test_extra_hash_map_contains_all_and_only_auxiliary_files(self):
        extras = {'context.json': b'{}', 'validation-feedback.json': b'evidence'}
        result = fleet.stage_guest_model_inputs(self.repo, {'paths': ['src/**']}, 'hello', extra_files=extras)
        self.assertEqual(result['extra_files_sha256'], {
            result['relative'] + '/' + name: hashlib.sha256(data).hexdigest()
            for name, data in extras.items()})

    def test_invalid_inputs_rejected_before_mutation(self):
        for pattern in ('../x', '/etc', 'x) Exec(*)', 'C:/x', 'x\\y'):
            with self.assertRaises(ValueError):
                fleet.stage_guest_model_inputs(self.repo, {'paths': [pattern]}, 'hello')
        with self.assertRaises(ValueError):
            fleet.stage_guest_model_inputs(self.repo, {'paths': ['src/**']}, 'x' * 32769)
        self.repo.make_directory.assert_not_called()

    def test_digest_mismatch_stops(self):
        self.repo.sha256.side_effect = None
        self.repo.sha256.return_value = 'wrong'
        with self.assertRaises(RuntimeError):
            fleet.stage_guest_model_inputs(self.repo, {'paths': ['src/**']}, 'hello')
        self.controller.stop.assert_called_once()


if __name__ == '__main__':
    unittest.main()
