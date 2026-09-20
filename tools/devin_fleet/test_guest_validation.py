"""Validation dispatch contracts, without executing generated code."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import fleet
from sandbox_repository import GuestRepository


class ValidationTests(unittest.TestCase):
    def test_retired_smoke_fails_before_process_or_file_activity(self):
        import guest_validation_smoke
        with patch('subprocess.Popen', side_effect=AssertionError('No process launch')), \
                patch('subprocess.run', side_effect=AssertionError('No process launch')), \
                patch.object(Path, 'open', side_effect=AssertionError('No file activity')):
            with self.assertRaisesRegex(RuntimeError, 'Retired role-VM validation'):
                guest_validation_smoke.main()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.controller = Mock()
        self.repo = GuestRepository(self.controller, '/home/agent/workspace/applications', self.root)
        self.log = self.root / 'validation.log'
        self.stop = self.root / 'FLEET_STOP'

    def test_guest_refused_before_vm_host_or_log_operations(self):
        with patch.object(fleet, 'supervised_run', side_effect=AssertionError('host fallback')) as host, \
                patch.object(fleet.subprocess, 'run', side_effect=AssertionError('host run')) as run, \
                patch.object(fleet.subprocess, 'Popen', side_effect=AssertionError('host launch')) as launch, \
                patch.object(Path, 'open', side_effect=AssertionError('log I/O')) as opening:
            with self.assertRaisesRegex(RuntimeError, 'Role-VM validation forbidden'):
                fleet.validate_repository(self.repo, ['-m', 'unittest'],
                    {'python': 'C:/host/python.exe'}, self.log, self.stop, 12)
        for guard in (host, run, launch, opening):
            guard.assert_not_called()
        self.assertEqual(self.controller.mock_calls, [])
        self.assertFalse(self.log.exists())

    def test_guest_refused_without_inspecting_settings_or_logs(self):
        # Neither a missing interpreter setting nor missing output can bypass
        # the type boundary or turn refusal into an attempted execution.
        with patch.object(fleet, 'supervised_run') as host, \
                patch.object(Path, 'read_bytes', side_effect=AssertionError('log read')) as read, \
                patch.object(Path, 'write_bytes', side_effect=AssertionError('log write')) as write:
            with self.assertRaisesRegex(RuntimeError, 'credential-free snapshot validation'):
                fleet.validate_repository(self.repo, [], {}, self.log, self.stop)
        host.assert_not_called()
        read.assert_not_called()
        write.assert_not_called()
        self.assertEqual(self.controller.mock_calls, [])

    def test_every_guest_root_refused_including_validation_named_root(self):
        for guest_root in ('/home/agent/workspace/machine',
                           '/home/agent/workspace/coordinator',
                           '/home/agent/workspace/validation', '/tmp/validation', '/workspace'):
            with self.subTest(guest_root=guest_root):
                repo = GuestRepository(self.controller, guest_root, self.root)
                with patch.object(fleet, 'supervised_run') as host:
                    with self.assertRaisesRegex(RuntimeError, 'Role-VM validation forbidden'):
                        fleet.validate_repository(repo, ['-m', 'unittest'], {}, self.log, self.stop)
                host.assert_not_called()
                self.assertEqual(self.controller.mock_calls, [])
                self.assertFalse(self.log.exists())

    def test_legacy_path_still_explicitly_local(self):
        with patch.object(fleet, 'supervised_run', return_value='local') as run:
            result = fleet.validate_repository(self.root, ['-m', 'unittest'],
                {'python': 'host-python'}, self.log, self.stop)
        self.assertEqual(result, 'local')
        self.assertEqual(run.call_args.args[0], ['host-python', '-X', 'utf8', '-m', 'unittest'])
        self.controller.execute.assert_not_called()


if __name__ == '__main__':
    unittest.main()
