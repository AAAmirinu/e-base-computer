"""Trusted synthetic commands only. No Docker/project source execution."""
import copy
import hashlib
import subprocess
import sys
import unittest
from unittest.mock import patch, Mock
import validation_source_smoke as runner


class CleanupTests(unittest.TestCase):
    def test_test_profiles_are_fixed_and_selector_is_strict(self):
        default = runner.test_arguments('owned')
        fixed = runner.test_arguments('owned', True)
        self.assertEqual(default[-5:], ['unittest', 'discover', '-s', 'tests', '-v'])
        self.assertEqual(fixed[-3:], ['unittest', '-v', 'test_add'])
        self.assertEqual(default[:-5], fixed[:-3])
        with self.assertRaisesRegex(TypeError, 'must be boolean'):
            runner.test_arguments('owned', 1)

    def receipt(self):
        return {'phase': 'tested', 'test': {'reason': 'exited', 'returncode': 0, 'reported_test_count': 3}}

    def test_success_journals_before_stop(self):
        value, states = self.receipt(), []
        def save():
            states.append(copy.deepcopy(value))
        with patch.object(runner, 'run', side_effect=['', '{"Running":false}']):
            runner.finish_container('owned', value, save)
        self.assertEqual([s['phase'] for s in states], ['cleanup_pending', 'complete'])
        self.assertTrue(value['test_command_succeeded'])
        self.assertFalse(value['validation_passed'])

    def test_journal_failure_still_attempts_stop(self):
        value = self.receipt()
        save = Mock(side_effect=[OSError('disk full'), None])
        with patch.object(runner, 'run', return_value='') as command, self.assertRaises(OSError):
            runner.finish_container('owned', value, save)
        command.assert_called_once_with(['docker', 'stop', '--time', '2', 'owned'])
        self.assertFalse(value['test_command_succeeded'])
        self.assertEqual(value['phase'], 'cleanup_failed')

    def test_selector_setup_failure_kills_client(self):
        for construction_failure in (True, False):
            process, selector = Mock(), Mock()
            process.poll.return_value = None
            selector.register.side_effect = OSError('register failed')
            with patch.object(runner.subprocess, 'Popen', return_value=process), patch.object(
                    runner.selectors, 'DefaultSelector', side_effect=OSError('init failed') if construction_failure else None,
                    return_value=selector), self.assertRaises(OSError):
                runner.bounded_test(['never run'])
            process.kill.assert_called_once()
            process.wait.assert_called_once_with(timeout=5)
            process.stdout.close.assert_called_once()

    def test_stop_failure_and_timeout_recorded(self):
        for error in (RuntimeError('stop failed'), subprocess.TimeoutExpired('stop', 30)):
            value, states = self.receipt(), []
            with patch.object(runner, 'run', side_effect=error), self.assertRaises(type(error)):
                runner.finish_container('owned', value, lambda: states.append(copy.deepcopy(value)))
            self.assertEqual(states[-1]['phase'], 'cleanup_failed')
            self.assertFalse(states[-1]['test_command_succeeded'])
            self.assertFalse(states[-1]['container_stopped'])

    def test_still_running_or_missing_observation_refused(self):
        for raw in ('{"Running":true}', '{}', 'bad'):
            value = self.receipt()
            with patch.object(runner, 'run', side_effect=['', raw]), self.assertRaises((RuntimeError, ValueError)):
                runner.finish_container('owned', value, lambda: None)
            self.assertEqual(value['phase'], 'cleanup_failed')

    def test_failed_timed_out_and_empty_tests_never_succeed(self):
        for test in ({'reason': 'timeout', 'returncode': 0, 'reported_test_count': 3},
                     {'reason': 'exited', 'returncode': 1, 'reported_test_count': 3},
                     {'reason': 'exited', 'returncode': 0, 'reported_test_count': 0},
                     {'reason': 'output_limit', 'returncode': -9, 'reported_test_count': 3}):
            value = {'phase': 'tested', 'test': test}
            with patch.object(runner, 'run', side_effect=['', '{"Running":false}']):
                runner.finish_container('owned', value, lambda: None)
            self.assertFalse(value['test_command_succeeded'])

    def test_interrupted_test_requires_inspection(self):
        value = {'phase': 'testing'}
        with patch.object(runner, 'run', side_effect=['', '{"Running":false}']):
            runner.finish_container('owned', value, lambda: None)
        self.assertEqual(value['phase'], 'inspection_required')
        self.assertFalse(value['test_command_succeeded'])


@unittest.skipUnless(sys.platform == 'linux', 'Linux pipe selector execution')
class BoundedProcessTests(unittest.TestCase):
    def execute(self, source):
        return runner.bounded_test([sys.executable, '-I', '-c', source])

    def test_normal_exit_and_hash(self):
        result = self.execute("print('hello')")
        self.assertEqual(result['reason'], 'exited')
        self.assertEqual(result['returncode'], 0)
        self.assertEqual(result['output_sha256'], hashlib.sha256(b'hello\n').hexdigest())

    def test_failed_exit(self):
        self.assertEqual(self.execute('raise SystemExit(7)')['returncode'], 7)

    def test_output_limit(self):
        with patch.object(runner, 'TEST_OUTPUT_LIMIT', 32):
            result = self.execute("import os; os.write(1,b'x'*100000)")
        self.assertEqual(result['reason'], 'output_limit')
        self.assertEqual(result['output'], 'x' * 32)

    def test_timeout_kills_client(self):
        with patch.object(runner, 'TEST_TIMEOUT', 0.2):
            result = self.execute('import time; time.sleep(10)')
        self.assertEqual(result['reason'], 'timeout')
        self.assertNotEqual(result['returncode'], 0)

    def test_closed_output_does_not_bypass_deadline(self):
        with patch.object(runner, 'TEST_TIMEOUT', 0.2):
            result = self.execute('import os,time; os.close(1); os.close(2); time.sleep(10)')
        self.assertEqual(result['reason'], 'timeout')


if __name__ == '__main__':
    unittest.main()
