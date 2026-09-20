"""Production helper dispatch tests; no guest code is executed on this host."""
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import fleet
from sandbox_repository import GuestRepository, GuestRepositoryError
from test_sandbox_repository import FakeController


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.controller = FakeController()
        self.repo = GuestRepository(self.controller, '/home/agent/repo', Path(self.temp.name))

    def test_sha_uses_guest_not_host(self):
        with patch.object(self.repo, 'git', return_value='a' * 40 + '\n') as git, \
                patch.object(fleet, 'run', side_effect=AssertionError('host execution')):
            self.assertEqual(fleet.sha(self.repo), 'a' * 40)
        git.assert_called_once_with('rev-parse', 'HEAD')

    def test_changes_preserve_names_and_disable_rename_collapse(self):
        with patch.object(self.repo, 'git', side_effect=[' a\nb \0old\0new\0', 'new\0z\0']) as git:
            self.assertEqual(fleet.changes(self.repo), [' a\nb ', 'new', 'old', 'z'])
        self.assertIn('--no-renames', git.call_args_list[0].args)

    def test_malformed_paths_fence(self):
        for data in ('a', 'a\0\0', '\0'):
            with patch.object(self.repo, 'git', side_effect=[data, '']), self.assertRaises(RuntimeError):
                fleet.changes(self.repo)
        self.assertEqual(self.controller.stops, 3)

    def test_guest_fingerprints_do_not_touch_host(self):
        with patch.object(self.repo, 'fingerprint', side_effect=['a' * 64, None]) as fingerprint:
            self.assertEqual(fleet.fingerprints(self.repo, ['a', 'deleted']), {'a': 'a' * 64, 'deleted': None})
        self.assertEqual(fingerprint.call_count, 2)

    def test_missing_and_empty_are_distinct(self):
        self.controller.data = b''
        self.assertIsNone(self.repo.fingerprint('missing'))
        expected = hashlib.sha256(b'').hexdigest()
        self.controller.data = expected.encode()
        self.assertEqual(self.repo.fingerprint('empty'), expected)
        self.assertEqual(self.controller.stops, 0)

    def test_bad_digest_fences(self):
        for data in (b'x' * 64, b'a' * 63):
            self.controller.data = data
            with self.assertRaises(GuestRepositoryError):
                self.repo.fingerprint('file')
        self.assertEqual(self.controller.stops, 2)

    def test_host_coercion_and_run_are_forbidden(self):
        for call in (lambda: str(self.repo), lambda: Path(self.repo), lambda: os.fspath(self.repo),
                     lambda: self.repo / 'file', lambda: fleet.run(['git'], cwd=self.repo),
                     lambda: fleet.run(['git', self.repo])):
            with self.assertRaises(TypeError):
                call()
        self.assertEqual(self.controller.calls, [])


if __name__ == '__main__':
    unittest.main()
