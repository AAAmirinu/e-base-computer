"""Synthetic data and mocks only; no CLI, VM or candidate-code execution."""
import copy
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import machine_eword_edit as edit
import machine_cli_smoke as smoke


class AuditWriteTests(unittest.TestCase):
    def setUp(self):
        self.target = Path('/tmp/synthetic/ecomputer.py')
        self.raw = b'# synthetic source data only\n'
        self.call = {'function_name': 'write', 'arguments': {
            'file_path': str(self.target), 'content': self.raw.decode()}}
        self.payload = {'steps': [{'source': 'agent', 'model_name': 'swe-2-high',
                                   'tool_calls': [self.call]}]}

    def audit(self):
        return edit.audit_write(self.payload, self.target, self.raw, smoke.EXPORT_MODEL_NAMES)

    def test_one_exact_write_and_fixed_model_accepted(self):
        for name in ('swe-2-high', 'SWE-2 High'):
            self.payload['steps'][0]['model_name'] = name
            self.assertIs(self.audit(), True)

    def test_other_models_rejected(self):
        for name in ('swe-2-medium', 'swe-2-max', 'other', None):
            with self.subTest(name=name):
                self.payload['steps'][0]['model_name'] = name
                self.assertIs(self.audit(), False)

    def test_reads_and_execution_rejected(self):
        for name in ('read', 'exec', 'edit', 'write_to_process'):
            with self.subTest(name=name):
                self.call['function_name'] = name
                self.assertIs(self.audit(), False)

    def test_extra_write_call_rejected(self):
        self.payload['steps'][0]['tool_calls'].append(copy.deepcopy(self.call))
        self.assertFalse(self.audit())

    def test_extra_read_call_rejected(self):
        self.payload['steps'][0]['tool_calls'].append({'function_name': 'read'})
        self.assertFalse(self.audit())

    def test_wrong_target_rejected(self):
        self.call['arguments']['file_path'] = '/tmp/synthetic/other.py'
        self.assertFalse(self.audit())

    def test_written_bytes_must_match_export(self):
        self.call['arguments']['content'] += 'extra'
        self.assertFalse(self.audit())

    def test_legacy_call_rejected(self):
        self.payload['steps'][0]['function_call'] = {'name': 'read'}
        self.assertFalse(self.audit())

    def test_nonagent_call_rejected(self):
        for source in ('system', 'user', 'tool'):
            with self.subTest(source=source):
                self.payload['steps'][0]['source'] = source
                self.assertFalse(self.audit())

    def test_missing_calls_or_agent_rejected(self):
        for payload in (None, {}, {'steps': []}, {'steps': ['invalid']},
                        {'steps': [{'source': 'agent', 'model_name': 'swe-2-high'}]},
                        {'steps': [{'source': 'system'}]}):
            with self.subTest(payload=payload):
                self.assertFalse(edit.audit_write(payload, self.target, self.raw,
                                                  smoke.EXPORT_MODEL_NAMES))

    def test_inherited_config_for_edit_preserves_read_and_shell_denial(self):
        config = smoke.file_probe_config(self.target.parent)
        config['permissions']['allow'] = ['Write(' + str(self.target) + ')']
        self.assertEqual(config['permissions']['allow'], ['Write(/tmp/synthetic/ecomputer.py)'])
        for rule in ('read', 'Read(**)', 'edit', 'exec', 'Exec(*)'):
            self.assertIn(rule, config['permissions']['deny'])


@unittest.skipUnless(os.name == 'posix' and hasattr(os, 'O_NOFOLLOW'), 'Linux file boundary')
class ReadBoundedTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.path = self.root / 'data'

    def test_exact_limit_bytes_accepted(self):
        self.path.write_bytes(b'a' * 64)
        self.assertEqual(edit.read_bounded(self.path, 64), b'a' * 64)

    def test_oversize_rejected(self):
        self.path.write_bytes(b'a' * 65)
        with self.assertRaises(ValueError):
            edit.read_bounded(self.path, 64)

    def test_symlink_rejected(self):
        target = self.root / 'target'
        target.write_bytes(b'data')
        self.path.symlink_to(target)
        with self.assertRaises(OSError):
            edit.read_bounded(self.path, 64)

    def test_hardlink_rejected(self):
        self.path.write_bytes(b'data')
        os.link(self.path, self.root / 'alias')
        with self.assertRaises(ValueError):
            edit.read_bounded(self.path, 64)

    def test_nonregular_file_rejected(self):
        self.path.mkdir()
        with self.assertRaises(ValueError):
            edit.read_bounded(self.path, 64)

    def test_foreign_owner_rejected(self):
        self.path.write_bytes(b'data')
        metadata = SimpleNamespace(st_mode=self.path.stat().st_mode, st_nlink=1,
                                   st_uid=os.getuid() + 1, st_size=4)
        with patch.object(edit.os, 'fstat', return_value=metadata):
            with self.assertRaises(ValueError):
                edit.read_bounded(self.path, 64)


class UniqueJsonTests(unittest.TestCase):
    def test_duplicate_model_and_calls_rejected(self):
        for raw in ('{"model_name":"other","model_name":"swe-2-high"}',
                    '{"step":{"tool_calls":[{}],"tool_calls":[]}}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                json.loads(raw, object_pairs_hook=edit.unique_pairs)

    def test_unique_fields_preserved(self):
        self.assertEqual(json.loads('{"a":[1],"b":true}', object_pairs_hook=edit.unique_pairs),
                         {'a': [1], 'b': True})


class MainFailureTests(unittest.TestCase):
    def invoke(self, source, catalog=None, error=None):
        output = io.StringIO()
        future_smoke = SimpleNamespace(EXPIRY=datetime(2099, 1, 1, tzinfo=timezone.utc),
                                       CLI='/fixed/devin-cli', MODEL='swe-2-high')
        completed = subprocess.CompletedProcess([], 0, stdout=json.dumps(catalog or {}).encode())
        with patch.object(edit.subprocess, 'run', return_value=completed, side_effect=error) as run, \
                patch.object(edit.subprocess, 'Popen', side_effect=AssertionError('No model permitted')) as launch, \
                patch.object(edit.Path, 'open', side_effect=AssertionError('No reservation permitted')) as opening, \
                patch('sys.stdout', output):
            edit.main(source, future_smoke)
        launch.assert_not_called()
        opening.assert_not_called()
        result = json.loads(output.getvalue())
        self.assertIs(result['passed'], False)
        self.assertIs(result['model_executed'], False)
        self.assertIs(result['candidate_executed'], False)
        self.assertIs(result['production_admitted'], False)
        self.assertNotIn('candidate_base64', result)
        return result, run

    def test_invalid_sources_fail_before_catalog(self):
        for source in (None, '', 'a' * (edit.LIMIT + 1), '\u3042' * (edit.LIMIT // 3 + 1)):
            with self.subTest(source_type=type(source).__name__):
                result, run = self.invoke(source)
                run.assert_not_called()
                self.assertEqual(result['error_type'], 'ValueError')

    def test_paid_or_missing_or_duplicate_model_fails_before_reservation(self):
        for variants in ([], [{'model_uid': 'swe-2-high', 'cost_tier': 'Paid'}],
                         [{'model_uid': 'swe-2-medium', 'cost_tier': 'Free'}],
                         [{'model_uid': 'swe-2-high', 'cost_tier': 'Free'}] * 2):
            with self.subTest(variants=variants):
                result, run = self.invoke('# data', {'families': [{'variants': variants}]})
                run.assert_called_once()
                self.assertEqual(result['error_type'], 'RuntimeError')

    def test_error_output_does_not_disclose_exception_message(self):
        secret = 'SYNTHETIC_PRIVATE_EXCEPTION'
        result, _ = self.invoke('# data', error=RuntimeError(secret))
        self.assertNotIn(secret, json.dumps(result))
        self.assertEqual(result['error_type'], 'RuntimeError')


if __name__ == '__main__':
    unittest.main()
