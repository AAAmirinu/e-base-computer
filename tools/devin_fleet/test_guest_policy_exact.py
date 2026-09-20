"""Pure guest policy and mocked staging; no model or guest execution."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import fleet
from sandbox_repository import GuestRepository


class GuestPolicyExactTests(unittest.TestCase):
    def setUp(self):
        self.path = '/home/agent/workspace/machine'
        self.entry = {'paths': ['src/**', 'tests/test_machine.py']}

    def test_exact_allowed_paths_without_shell_rules(self):
        policy = fleet.guest_permission_config(self.path, self.entry)
        self.assertEqual(policy['permissions']['allow'], [
            'Read(' + self.path + '/**)',
            'Write(' + self.path + '/src/**)',
            'Write(' + self.path + '/tests/test_machine.py)',
            'Write(' + self.path + '/.fleet/**)'])

    def test_exec_and_sensitive_control_files_remain_denied(self):
        policy = fleet.guest_permission_config(self.path, self.entry)
        legacy = fleet.permission_config(self.path, self.entry)
        self.assertEqual(policy['permissions']['deny'], legacy['permissions']['deny'] + [
            'exec', 'Exec(*)', 'Write(' + self.path + '/.fleet/control-*/**)'])
        for rule in ('Write(**/.git/**)', 'Write(**/.devin/**)',
                     'Read(**/.env*)', 'Read(**/*credentials*)'):
            self.assertIn(rule, policy['permissions']['deny'])

    def test_external_config_imports_disabled_and_model_fixed(self):
        policy = fleet.guest_permission_config(self.path, self.entry)
        self.assertEqual(policy['read_config_from'], {'cursor': False, 'windsurf': False, 'claude': False})
        self.assertEqual(policy['agent'], {'model': fleet.MODEL})
        self.assertEqual(policy['notify'], 'never')

    def test_legacy_read_exec_allowances_are_unchanged(self):
        before = fleet.permission_config(self.path, self.entry)
        fleet.guest_permission_config(self.path, self.entry)
        self.assertEqual(fleet.permission_config(self.path, self.entry), before)
        self.assertEqual([rule for rule in before['permissions']['allow'] if rule.startswith('Exec(')],
                         ['Exec(' + command + ')' for command in fleet.READ_COMMANDS])
        self.assertNotIn('Exec(*)', before['permissions']['deny'])

    def test_returned_policy_does_not_mutate_input_or_future_policies(self):
        original = copy.deepcopy(self.entry)
        policy = fleet.guest_permission_config(self.path, self.entry)
        expected = copy.deepcopy(policy)
        policy['permissions']['allow'].append('Exec(*)')
        policy['permissions']['deny'].clear()
        self.assertEqual(self.entry, original)
        self.assertEqual(fleet.guest_permission_config(self.path, self.entry), expected)

    def test_stage_uses_shared_helper_and_preserves_exact_serialized_policy(self):
        with tempfile.TemporaryDirectory() as temporary:
            controller = Mock()
            repo = GuestRepository(controller, self.path, Path(temporary))
            files = {}
            repo.make_directory = Mock()
            repo.write_bytes = Mock(side_effect=files.__setitem__)
            repo.sha256 = Mock(side_effect=lambda path: hashlib.sha256(files[path]).hexdigest())
            expected = fleet.guest_permission_config(self.path, self.entry)
            with patch.object(fleet, 'guest_permission_config', wraps=fleet.guest_permission_config) as helper:
                staged = fleet.stage_guest_model_inputs(repo, self.entry, 'synthetic prompt')
            helper.assert_called_once_with(self.path, self.entry)
            raw = files[staged['relative'] + '/config.json']
            self.assertEqual(json.loads(raw), expected)
            self.assertEqual(raw, (json.dumps(expected, ensure_ascii=False, indent=2) + '\n').encode())
            self.assertEqual(staged['config_sha256'], hashlib.sha256(raw).hexdigest())
            controller.execute.assert_not_called()


if __name__ == '__main__':
    unittest.main()
