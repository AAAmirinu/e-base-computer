import os
import subprocess
import unittest
from unittest.mock import Mock, patch

if os.name == 'posix':
    import daemon_boundary_smoke as smoke


@unittest.skipUnless(os.name == 'posix', 'Dedicated Linux controller')
class CommandTests(unittest.TestCase):
    def test_policy_denial_status_is_only_explicitly_accepted(self):
        process = Mock(returncode=1)
        process.communicate.return_value = ('{"allowed":false}', '')
        with patch.object(smoke.subprocess, 'Popen', return_value=process):
            with self.assertRaises(RuntimeError):
                smoke.command(['probe'])
            self.assertEqual(smoke.command(['probe'], allowed_codes=(0, 1)), '{"allowed":false}')

    def test_timeout_kills_and_reaps_client_group(self):
        process = Mock(pid=123)
        process.communicate.side_effect = [subprocess.TimeoutExpired('probe', 1), ('', '')]
        with patch.object(smoke.subprocess, 'Popen', return_value=process) as spawn, \
                patch.object(smoke.os, 'killpg') as kill:
            with self.assertRaises(subprocess.TimeoutExpired):
                smoke.command(['probe'], timeout=1)
        self.assertTrue(spawn.call_args.kwargs['start_new_session'])
        kill.assert_called_once_with(123, smoke.signal.SIGKILL)
        self.assertEqual(process.communicate.call_count, 2)

    def test_already_exited_group_is_still_reaped(self):
        process = Mock(pid=123)
        process.communicate.side_effect = [KeyboardInterrupt(), ('', '')]
        with patch.object(smoke.subprocess, 'Popen', return_value=process), \
                patch.object(smoke.os, 'killpg', side_effect=ProcessLookupError):
            with self.assertRaises(KeyboardInterrupt):
                smoke.command(['probe'])
        self.assertEqual(process.communicate.call_count, 2)


if __name__ == '__main__':
    unittest.main()
