"""Offline saved-evidence tests using synthetic bytes and mocked I/O only."""
from contextlib import ExitStack
import hashlib
import io
import json
from pathlib import Path
import stat
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import machine_eword_edit as edit


class SavedEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.work = Path('/tmp/e-base-eword-edit-synthetic')
        self.source = b'# SYNTHETIC_PRIVATE_SOURCE\n'
        self.marker = json.dumps({'phase': 'reserved', 'model': 'swe-2-high',
                                  'input_sha256': edit.INPUT_SHA}).encode()
        self.export = json.dumps({'steps': [{'source': 'agent', 'model_name': 'SWE-2 High',
            'tool_calls': [{'function_name': 'write', 'arguments': {
                'file_path': str(self.work / 'ecomputer.py'),
                'content': self.source.decode()}}]}]}).encode()
        self.candidate_digest = hashlib.sha256(self.source).hexdigest()
        self.export_digest = hashlib.sha256(self.export).hexdigest()
        self.directories = [self.work]
        self.metadata = SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_uid=123)
        self.read_error = None

    def read(self, path, limit):
        if self.read_error:
            raise self.read_error
        if path.name == 'e-base-machine-eword-edit-v1.json':
            self.assertEqual(limit, 1024)
            return self.marker
        if path == self.work / 'ecomputer.py':
            self.assertEqual(limit, edit.LIMIT)
            return self.source
        if path == self.work / 'export.json':
            self.assertEqual(limit, 1024 * 1024)
            return self.export
        raise AssertionError('Unexpected read')

    def invoke(self):
        output = io.StringIO()
        smoke = SimpleNamespace(MODEL='swe-2-high',
                                EXPORT_MODEL_NAMES=frozenset(('swe-2-high', 'SWE-2 High')))
        with ExitStack() as stack:
            stack.enter_context(patch.object(edit, 'CANDIDATE_SHA', self.candidate_digest))
            stack.enter_context(patch.object(edit, 'EXPORT_SHA', self.export_digest))
            reader = stack.enter_context(patch.object(edit, 'read_bounded', side_effect=self.read))
            stack.enter_context(patch.object(edit.Path, 'glob', return_value=iter(self.directories)))
            stack.enter_context(patch.object(edit.Path, 'lstat', return_value=self.metadata))
            stack.enter_context(patch.object(edit.os, 'getuid', return_value=123, create=True))
            guards = [stack.enter_context(patch.object(owner, name, side_effect=AssertionError('Offline only')))
                      for owner, name in ((edit.subprocess, 'run'), (edit.subprocess, 'Popen'),
                                          (edit.Path, 'open'), (edit.Path, 'unlink'))]
            stack.enter_context(patch('sys.stdout', output))
            edit.inspect_saved(smoke)
        for guard in guards:
            guard.assert_not_called()
        result = json.loads(output.getvalue())
        for key in ('model_executed', 'candidate_executed', 'resume_available', 'production_admitted'):
            self.assertIs(result[key], False)
        self.assertNotIn('candidate_base64', result)
        self.assertNotIn('SYNTHETIC_PRIVATE', output.getvalue())
        self.assertNotIn(str(self.work), output.getvalue())
        return result, reader

    def test_valid_saved_evidence_without_launch_or_secret_output(self):
        result, reader = self.invoke()
        self.assertTrue(result['passed'])
        self.assertTrue(result['reservation_preserved'])
        self.assertTrue(result['tool_scope_verified'])
        self.assertEqual(result['candidate_sha256'], self.candidate_digest)
        self.assertEqual(result['export_sha256'], self.export_digest)
        self.assertEqual(result['reservation_sha256'], hashlib.sha256(self.marker).hexdigest())
        self.assertEqual(reader.call_count, 3)

    def test_broken_marker_stops_before_candidate_reads(self):
        self.marker = b'{SYNTHETIC_PRIVATE_BROKEN'
        result, reader = self.invoke()
        self.assertFalse(result['passed'])
        self.assertEqual(reader.call_count, 1)

    def test_marker_mismatch_rejected(self):
        for field, value in (('phase', 'complete'), ('model', 'other'), ('input_sha256', 'bad')):
            with self.subTest(field=field):
                marker = {'phase': 'reserved', 'model': 'swe-2-high', 'input_sha256': edit.INPUT_SHA}
                marker[field] = value
                self.marker = json.dumps(marker).encode()
                result, reader = self.invoke()
                self.assertFalse(result['passed'])
                self.assertEqual(reader.call_count, 1)

    def test_duplicate_marker_keys_rejected(self):
        self.marker = (b'{"phase":"bad","phase":"reserved","model":"swe-2-high",'
                       b'"input_sha256":"' + edit.INPUT_SHA.encode() + b'"}')
        result, _ = self.invoke()
        self.assertFalse(result['passed'])

    def test_missing_or_extra_directory_rejected(self):
        for directories in ([], [self.work, Path('/tmp/e-base-eword-edit-extra')]):
            with self.subTest(count=len(directories)):
                self.directories = directories
                result, reader = self.invoke()
                self.assertFalse(result['passed'])
                self.assertEqual(reader.call_count, 1)

    def test_unsafe_directory_rejected(self):
        for mode, uid in ((stat.S_IFLNK | 0o700, 123), (stat.S_IFDIR | 0o755, 123),
                          (stat.S_IFDIR | 0o700, 999)):
            with self.subTest(mode=mode, uid=uid):
                self.metadata = SimpleNamespace(st_mode=mode, st_uid=uid)
                result, reader = self.invoke()
                self.assertFalse(result['passed'])
                self.assertEqual(reader.call_count, 1)

    def test_candidate_hash_mismatch_rejected(self):
        self.source += b'# altered'
        result, _ = self.invoke()
        self.assertFalse(result['passed'])

    def test_export_hash_mismatch_rejected(self):
        self.export += b' '
        result, _ = self.invoke()
        self.assertFalse(result['passed'])

    def test_digest_match_does_not_bypass_tool_audit(self):
        self.export = self.export.replace(b'"write"', b'"exec"')
        self.export_digest = hashlib.sha256(self.export).hexdigest()
        result, _ = self.invoke()
        self.assertFalse(result['passed'])

    def test_exception_details_not_exported(self):
        self.read_error = OSError('SYNTHETIC_PRIVATE_FAILURE')
        result, _ = self.invoke()
        self.assertFalse(result['passed'])
        self.assertEqual(result['error_type'], 'OSError')


if __name__ == '__main__':
    unittest.main()
