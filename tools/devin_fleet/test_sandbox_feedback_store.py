import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from validation_feedback_store import persist_feedback


class FeedbackStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.value = {'schema': 1, 'hold_cleared': False, 'message': 'untrusted data'}

    def test_create_and_repeat(self):
        first = persist_feedback(self.root, self.value)
        second = persist_feedback(self.root, self.value)
        self.assertTrue(first['created'])
        self.assertFalse(second['created'])
        self.assertEqual(first['sha256'], second['sha256'])
        self.assertFalse(second['delivered'])
        self.assertEqual(json.loads(Path(first['path']).read_bytes()), self.value)

    def test_partial_preserved(self):
        path = self.root / 'failure-feedback.json'
        path.write_bytes(b'{')
        with self.assertRaises(ValueError):
            persist_feedback(self.root, self.value)
        self.assertEqual(path.read_bytes(), b'{')

    def test_conflict_preserved(self):
        first = persist_feedback(self.root, self.value)
        before = Path(first['path']).read_bytes()
        with self.assertRaises(ValueError):
            persist_feedback(self.root, {'different': True})
        self.assertEqual(Path(first['path']).read_bytes(), before)

    def test_file_sync_failure_not_acknowledged_and_retry(self):
        with patch('validation_feedback_store.os.fsync', side_effect=OSError('injected')):
            with self.assertRaises(OSError):
                persist_feedback(self.root, self.value)
        self.assertFalse(persist_feedback(self.root, self.value)['created'])

    def test_directory_sync_failure_and_retry(self):
        with patch('validation_feedback_store._sync_directory', side_effect=OSError('injected')):
            with self.assertRaises(OSError):
                persist_feedback(self.root, self.value)
        self.assertFalse(persist_feedback(self.root, self.value)['created'])

    @unittest.skipUnless(os.name == 'posix', 'Linux filesystem boundary')
    def test_link_and_permissions(self):
        other = self.root / 'other'
        other.write_bytes(b'unchanged')
        path = self.root / 'failure-feedback.json'
        path.symlink_to(other)
        with self.assertRaises(ValueError):
            persist_feedback(self.root, self.value)
        self.assertEqual(other.read_bytes(), b'unchanged')

    @unittest.skipUnless(os.name == 'posix', 'Linux filesystem boundary')
    def test_fifo_rejected_without_blocking(self):
        os.mkfifo(self.root / 'failure-feedback.json', 0o600)
        with self.assertRaises(ValueError):
            persist_feedback(self.root, self.value)

    @unittest.skipUnless(os.name == 'posix', 'Linux filesystem boundary')
    def test_hardlink_rejected(self):
        first = persist_feedback(self.root, self.value)
        os.link(first['path'], self.root / 'alias')
        with self.assertRaises(ValueError):
            persist_feedback(self.root, self.value)


if __name__ == '__main__':
    unittest.main()
