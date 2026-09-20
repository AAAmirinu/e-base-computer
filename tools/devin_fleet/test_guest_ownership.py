"""Guest ownership protocol checks; no VM or guest program runs on the host."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import fleet
from sandbox_repository import GuestRepository, GuestRepositoryError, _GUEST_CODE
from test_sandbox_repository import FakeController


class GuestOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.controller = FakeController()
        self.repo = GuestRepository(self.controller, '/home/agent/repo', Path(self.temp.name))

    def test_kind_routes_fixed_guest_code_with_bounded_output(self):
        for kind in ('regular', 'missing', 'symlink', 'directory', 'hardlink', 'other'):
            with self.subTest(kind=kind):
                self.controller.data = kind.encode('ascii')
                self.assertEqual(self.repo.path_kind('src/file.py'), kind)
                argv, options = self.controller.calls[-1]
                self.assertEqual(argv[:4], ['python3', '-I', '-c', _GUEST_CODE])
                self.assertEqual(options['cwd'], '/')
                self.assertEqual(json.loads(argv[5]), dict(
                    operation='kind', root='/home/agent/repo', limit=16, relative='src/file.py'))
        self.assertEqual(self.controller.stops, 0)

    def test_regular_and_missing_owned_paths_are_accepted(self):
        with patch.object(self.repo, 'path_kind', side_effect=['regular', 'missing']) as kind:
            fleet.check_owned_changes(self.repo, ['src/new.py', 'src/deleted.py'], ['src/*'], 'machine')
        self.assertEqual([c.args for c in kind.call_args_list], [('src/new.py',), ('src/deleted.py',)])
        self.assertEqual(self.controller.stops, 0)

    def test_unowned_path_rejected_before_metadata(self):
        for path in ('other/file.py', '../src/file.py', '.git/config', 'AGENTS.md'):
            with self.subTest(path=path), patch.object(self.repo, 'path_kind') as kind:
                with self.assertRaisesRegex(RuntimeError, 'unowned path'):
                    fleet.check_owned_changes(self.repo, [path], ['src/*'], 'machine')
                kind.assert_not_called()
        self.assertEqual(self.controller.stops, 4)
        self.assertEqual(self.controller.calls, [])

    def test_linked_and_special_owned_paths_stop_and_refuse(self):
        for kind in ('symlink', 'hardlink', 'directory', 'other'):
            with self.subTest(kind=kind):
                self.controller.data = kind.encode('ascii')
                before = self.controller.stops
                with self.assertRaisesRegex(RuntimeError, 'linked or non-regular'):
                    fleet.check_owned_changes(self.repo, ['src/file'], ['src/*'], 'machine')
                self.assertEqual(self.controller.stops, before + 1)

    def test_malformed_kind_stops_instead_of_becoming_regular(self):
        for data in (b'', b'file', b'REGULAR', b'regular\n', b'\xff'):
            with self.subTest(data=data):
                self.controller.data = data
                before = self.controller.stops
                with self.assertRaises(GuestRepositoryError):
                    self.repo.path_kind('src/file')
                self.assertEqual(self.controller.stops, before + 1)

    def test_invalid_relative_paths_never_dispatch(self):
        for path in ('../file', '/etc/passwd', 'src//file', 'src/./file', 'src\\file'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.repo.path_kind(path)
        self.assertEqual(self.controller.calls, [])

    def test_ownership_uses_no_host_path_coercion_or_host_commands(self):
        self.controller.data = b'regular'
        with patch.object(GuestRepository, '__fspath__', side_effect=AssertionError('host coercion')), \
                patch.object(GuestRepository, '__truediv__', create=True, side_effect=AssertionError('host path join')), \
                patch.object(fleet, 'run', side_effect=AssertionError('host execution')):
            fleet.check_owned_changes(self.repo, ['src/file'], ['src/*'], 'machine')
        self.assertEqual(len(self.controller.calls), 1)
        self.assertEqual(self.controller.stops, 0)

    def test_metadata_failure_fences_and_aborts_remaining_checks(self):
        with patch.object(self.repo, 'path_kind', side_effect=RuntimeError('metadata unavailable')) as kind:
            with self.assertRaisesRegex(RuntimeError, 'metadata unavailable'):
                fleet.check_owned_changes(self.repo, ['src/a', 'src/b'], ['src/*'], 'machine')
        kind.assert_called_once_with('src/a')
        self.assertEqual(self.controller.stops, 1)


if __name__ == '__main__':
    unittest.main()
