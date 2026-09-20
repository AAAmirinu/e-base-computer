"""Model transport contract tests. No actual Devin/model invocation."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

import fleet
from sandbox_repository import GuestRepository


class GuestModelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.controller = Mock()
        self.controller.sandbox_id = 'sandbox-id'
        self.controller.name = 'e-base-machine'
        self.controller.execute.return_value = subprocess.CompletedProcess([], 0, '', '')
        self.repo = GuestRepository(self.controller, '/home/agent/workspace/machine', self.root)
        base = self.repo.guest_root
        self.args = ['/home/agent/.local/bin/devin-cli', '--config', base + '/config.json', '--model', 'swe-2-high',
            '--permission-mode', 'normal', '--respect-workspace-trust', 'false',
            '--export', base + '/fresh-export.json', '--prompt-file', base + '/prompt.md', '--print']
        self.payload = {'session_id': 'new-session', 'steps': [{'source': 'agent', 'model_name': 'swe-2-high'}]}
        self.config = {'version': 1, 'permissions': {'allow': [], 'deny': ['exec', 'Exec(*)']}}
        self.config_raw = json.dumps(self.config).encode()
        self.config_digest = hashlib.sha256(self.config_raw).hexdigest()
        for context in (patch.object(fleet, 'EXPIRY', datetime(2030, 1, 1, tzinfo=timezone.utc)),
                        patch.object(GuestRepository, 'fingerprint', return_value=None),
                        patch.object(GuestRepository, 'sha256', side_effect=lambda path: self.config_digest if path == 'config.json' else 'a' * 64),
                        patch.object(GuestRepository, 'read_bytes', side_effect=lambda path, **k: self.config_raw if path == 'config.json' else json.dumps(self.payload).encode()),
                        patch.object(fleet, 'supervised_run', side_effect=AssertionError('host fallback'))):
            context.start()
            self.addCleanup(context.stop)

    def invoke(self, args=None, digest=None, extras=None):
        return fleet.execute_model_attempt(self.repo, args or self.args, self.root / 'out.log',
            self.root / 'STOP', 30, self.root / 'operation.json', 'machine', 0, self.config_digest if digest is None else digest,
            migration_epoch='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', sequence=0,
            expected_prompt_sha256='a' * 64, expected_extra_files_sha256=extras)

    def test_extra_hashes_checked_twice_and_recorded(self):
        extras = {'validation-feedback.json': 'b'*64}
        def fingerprint(path, **kwargs):
            return extras.get(path)
        with patch.object(GuestRepository, 'fingerprint', side_effect=fingerprint) as check:
            self.invoke(extras=extras)
        calls = [c for c in check.call_args_list if c.args[0] == 'validation-feedback.json']
        self.assertEqual(len(calls), 2)
        receipt = json.loads((self.root/'operation.json').read_text())
        self.assertEqual(receipt['extra_files_sha256'], extras)

    def test_hash_approved_legacy_shell_policy_cannot_launch(self):
        self.config['permissions'] = {'allow': ['Exec(cat)'], 'deny': []}
        self.config_raw = json.dumps(self.config).encode()
        self.config_digest = hashlib.sha256(self.config_raw).hexdigest()
        with self.assertRaisesRegex(ValueError, 'shell execution'):
            self.invoke()
        self.controller.execute.assert_not_called()
        self.controller.stop.assert_called_once()
        self.assertFalse((self.root / 'operation.json').exists())

    def test_policy_read_bytes_must_match_approved_hash(self):
        self.config_raw += b' '
        with self.assertRaisesRegex(ValueError, 'approved digest'):
            self.invoke()
        self.controller.execute.assert_not_called()
        self.controller.stop.assert_called_once()

    def test_policy_schema_and_duplicate_keys_fail_closed(self):
        invalid = [b'{"version":1,"version":1}', b'[]',
                   b'{"version":true,"permissions":{"allow":[],"deny":["exec","Exec(*)"]}}']
        for permissions in ({'allow': ['exec'], 'deny': ['exec', 'Exec(*)']},
                            {'allow': ['*'], 'deny': ['exec', 'Exec(*)']},
                            {'allow': [' Exec(cat) '], 'deny': ['exec', 'Exec(*)']},
                            {'allow': [], 'deny': ['exec']},
                            {'allow': [None], 'deny': ['exec', 'Exec(*)']}):
            invalid.append(json.dumps({'version':1, 'permissions':permissions}).encode())
        for raw in invalid:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                fleet.verify_guest_file_tool_policy(raw, hashlib.sha256(raw).hexdigest())

    def test_missing_extra_prevents_launch(self):
        with self.assertRaises(RuntimeError):
            self.invoke(extras={'feedback.json': 'b'*64})
        self.controller.execute.assert_not_called()
        self.controller.stop.assert_called_once()

    def test_changed_extra_rejects_result(self):
        count = 0
        def fingerprint(path, **kwargs):
            nonlocal count
            if path == 'feedback.json':
                count += 1
                return 'b'*64 if count == 1 else 'c'*64
            return None
        with patch.object(GuestRepository, 'fingerprint', side_effect=fingerprint), self.assertRaises(RuntimeError):
            self.invoke(extras={'feedback.json': 'b'*64})
        self.assertEqual(json.loads((self.root/'operation.json').read_text())['phase'], 'prepared')
        self.controller.stop.assert_called()

    def test_invalid_extra_paths_and_hashes(self):
        for extras in ([], {'../x': 'b'*64}, {'elsewhere/x': 'b'*64},
                       {'config.json': 'b'*64}, {'fresh-export.json': 'b'*64}, {'x': True}):
            with self.subTest(extras=extras), self.assertRaises(ValueError):
                self.invoke(extras=extras)
        self.controller.execute.assert_not_called()

    def test_verified_export_receipt_and_global_stop(self):
        _, result = self.invoke()
        self.assertEqual(result, self.payload)
        receipt = json.loads((self.root / 'operation.json').read_text())
        self.assertEqual(receipt['phase'], 'export_verified')
        self.assertEqual(receipt['sandbox_id'], 'sandbox-id')
        self.assertNotIn('pid', receipt)
        self.assertEqual(len(receipt['export_sha256']), 64)
        self.assertEqual(self.controller.execute.call_args.kwargs['external_stop'], self.root / 'STOP')
        self.assertEqual(self.controller.execute.call_args.args[0][0], '/home/agent/.local/bin/devin-cli')

    def test_guest_rejects_path_lookup_and_alternate_executables(self):
        for executable in ('devin', 'devin-cli', '/usr/local/bin/devin',
                           '/home/agent/.local/bin/../bin/devin-cli',
                           '/home/agent/workspace/machine/devin-cli'):
            with self.subTest(executable=executable), self.assertRaises(ValueError):
                self.invoke([executable] + self.args[1:])
        self.controller.execute.assert_not_called()
        self.assertFalse((self.root / 'operation.json').exists())

    def test_legacy_host_executable_remains_caller_selected(self):
        args = ['C:/legacy/devin.exe', '--export', str(self.root / 'legacy-export.json')]
        proc = subprocess.CompletedProcess(args, 0, '', '')
        with patch.object(fleet, 'supervised_run', return_value=proc) as host_run:
            result, export = fleet.execute_model_attempt(self.root, args, self.root / 'host.log',
                self.root / 'STOP', 30, self.root / 'host-operation.json', 'machine', 0)
        self.assertIs(result, proc)
        self.assertEqual(export, {})
        self.assertEqual(host_run.call_args.args[0], args)
        self.controller.execute.assert_not_called()

    def test_reject_policy_and_host_paths_before_execution(self):
        bad = [self.args + ['--permission-mode', 'auto'], self.args + ['--dangerous'],
               ['C:/devin.exe'] + self.args[1:]]
        for old, new in [('normal', 'auto'), ('swe-2-high', 'other'),
                         (self.args[2], 'C:/config.json'), (self.args[2], self.repo.guest_root + '/../config')]:
            bad.append([new if x == old else x for x in self.args])
        for args in bad:
            with self.assertRaises(ValueError):
                self.invoke(args)
        self.controller.execute.assert_not_called()

    def test_stale_export_and_config_mismatch_do_not_launch(self):
        with patch.object(GuestRepository, 'fingerprint', return_value='b' * 64), self.assertRaises(RuntimeError):
            self.invoke()
        with self.assertRaises(RuntimeError):
            self.invoke(digest='b' * 64)
        self.controller.execute.assert_not_called()

    def test_wrong_model_fences_and_keeps_prepared_receipt(self):
        self.payload['steps'][0]['model_name'] = 'other'
        with self.assertRaises(RuntimeError):
            self.invoke()
        self.controller.stop.assert_called_once()
        self.assertEqual(json.loads((self.root / 'operation.json').read_text())['phase'], 'prepared')

    def test_resumed_identity_must_match(self):
        with self.assertRaises(ValueError):
            self.invoke(self.args + ['--resume', 'old-session'])
        self.controller.stop.assert_called_once()

    def test_existing_receipt_blocks_automatic_retry(self):
        self.invoke()
        with self.assertRaises(RuntimeError):
            self.invoke()
        self.assertEqual(self.controller.execute.call_count, 1)


if __name__ == '__main__':
    unittest.main()
