"""Bounded, host-portable checks for the targeted lock bootstrap helper."""
from pathlib import Path
import stat
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import lock_bootstrap_probe as probe


class LockBootstrapTests(unittest.TestCase):
    def metadata(self, **changes):
        values = dict(st_mode=stat.S_IFREG | 0o600, st_uid=1000,
                      st_gid=1000, st_nlink=1, st_dev=23, st_ino=456)
        values.update(changes)
        return SimpleNamespace(**values)

    def assert_rejected(self, **changes):
        with patch.object(Path, 'lstat', return_value=self.metadata(**changes)), \
                self.assertRaisesRegex(RuntimeError, 'refusing repair/replacement'):
            probe.identity()

    def test_valid_regular_file_returns_device_and_inode(self):
        with patch.object(Path, 'lstat', return_value=self.metadata()) as inspect:
            self.assertEqual(probe.identity(), (23, 456))
        inspect.assert_called_once_with()

    def test_symlink_is_rejected_without_following(self):
        self.assert_rejected(st_mode=stat.S_IFLNK | 0o600)

    def test_other_nonregular_objects_are_rejected(self):
        for kind in (stat.S_IFDIR, stat.S_IFIFO, stat.S_IFSOCK,
                     stat.S_IFCHR, stat.S_IFBLK):
            with self.subTest(kind=kind):
                self.assert_rejected(st_mode=kind | 0o600)

    def test_wrong_user_is_rejected(self):
        self.assert_rejected(st_uid=0)

    def test_wrong_group_is_rejected(self):
        self.assert_rejected(st_gid=0)

    def test_wrong_permissions_are_rejected(self):
        for mode in (0o400, 0o644, 0o660, 0o777, 0o4600):
            with self.subTest(mode=mode):
                self.assert_rejected(st_mode=stat.S_IFREG | mode)

    def test_multiple_or_zero_links_are_rejected(self):
        for count in (0, 2):
            with self.subTest(count=count):
                self.assert_rejected(st_nlink=count)

    def test_missing_file_is_not_silently_accepted(self):
        with patch.object(Path, 'lstat', side_effect=FileNotFoundError), \
                self.assertRaises(FileNotFoundError):
            probe.identity()

    def test_create_only_runs_exact_targeted_command(self):
        with patch.object(probe.subprocess, 'run') as run:
            probe.create()
        run.assert_called_once_with(
            ['/usr/bin/systemd-tmpfiles', '--create',
             '/etc/tmpfiles.d/e-base-fleet.conf'],
            check=True, timeout=15, capture_output=True, text=True)
        command = run.call_args.args[0]
        self.assertNotIn('--clean', command)
        self.assertNotIn('--remove', command)

    def test_create_errors_are_not_hidden(self):
        for error in (subprocess.CalledProcessError(1, 'systemd-tmpfiles'),
                      subprocess.TimeoutExpired('systemd-tmpfiles', 15)):
            with self.subTest(error=type(error).__name__), \
                    patch.object(probe.subprocess, 'run', side_effect=error), \
                    self.assertRaises(type(error)):
                probe.create()


if __name__ == '__main__':
    unittest.main()
