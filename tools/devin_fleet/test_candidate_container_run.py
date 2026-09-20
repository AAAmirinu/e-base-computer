"""Offline execution lifecycle tests; no VM, subprocess, or source execution."""
import builtins
import copy
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import candidate_container_run as runner


@unittest.skipUnless(os.name == 'posix', 'Dedicated controller is Linux-only')
class CandidateContainerRunTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.work = self.root / ('candidate-attempt-' + 'a' * 32)
        self.lock = self.root / 'global.lock'
        self.lock.touch()
        self.patch(runner, 'ROOT', self.root)
        self.namespace = self.patch(runner, 'require_managed_namespace')
        self.patch(runner, 'open', side_effect=self.open_lock, create=True)
        self.patch(runner.fcntl, 'flock')
        self.old_target = runner.policy.NAME, runner.policy.UUID
        self.stopped = self.patch(runner.policy, 'stopped')
        self.rules = self.patch(runner.policy, 'rules', return_value=[{'resources': ['**']}])
        self.patch(runner.policy, 'scoped_deny', return_value=True)
        self.allowed = self.patch(runner.policy, 'allowed', return_value=False)
        self.stop = self.patch(runner.policy, 'run')
        self.admission = Mock()
        self.handlers = {sig: object() for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
        self.original_handlers = dict(self.handlers)
        self.patch(runner.signal, 'signal', side_effect=self.change_handler)
        self.guest = dict(passed=True, container_stopped=True, image_id=runner.IMAGE,
                          boundary=dict(observations_verified=True, full_isolation_accepted=False))
        self.command = self.patch(runner.subprocess, 'run', side_effect=self.run_command)

    def patch(self, owner, name, *args, **kwargs):
        context = patch.object(owner, name, *args, **kwargs)
        result = context.start()
        self.addCleanup(context.stop)
        return result

    def open_lock(self, path, mode):
        self.assertEqual(path, '/tmp/e-base-devin-fleet-global.lock')
        self.assertEqual(mode, 'r')
        return builtins.open(self.lock, mode)

    def change_handler(self, sig, handler):
        previous = self.handlers[sig]
        self.handlers[sig] = handler
        return previous

    def run_command(self, argv, **kwargs):
        self.assertEqual(argv[:len(runner.SBX)], runner.SBX)
        self.assertEqual(kwargs['input'], b'synthetic trusted packet')
        self.assertEqual(kwargs['timeout'], 180)
        self.assertIs(kwargs['preexec_fn'], runner._limit_logs)
        self.assertTrue((self.work / 'receipt.json').is_file())
        kwargs['stdout'].write(json.dumps(self.guest).encode())
        kwargs['stderr'].write(b'synthetic diagnostics')
        return SimpleNamespace(returncode=0)

    def invoke(self, **overrides):
        args = dict(packet=b'synthetic trusted packet', work=self.work, admission=self.admission)
        args.update(overrides)
        return runner.execute(**args)

    def receipt(self):
        return json.loads((self.work / 'receipt.json').read_bytes())

    def assert_restored(self):
        self.assertEqual((runner.policy.NAME, runner.policy.UUID), self.old_target)
        self.assertEqual(self.handlers, self.original_handlers)

    def assert_stopped_hold(self, error_type):
        saved = self.receipt()
        self.assertEqual(saved['phase'], 'inspection_required')
        self.assertTrue(saved['all_vms_stopped'])
        self.assertEqual(saved['error_type'], error_type)
        self.assertFalse(saved['automatic_resume'])
        self.stop.assert_called_once_with('stop', 'e-base-validation')
        self.assert_restored()

    def test_success_requires_shutdown_and_restores_process_state(self):
        result = self.invoke()
        self.assertEqual(result, dict(directory=str(self.work), guest=self.guest))
        self.assertEqual(self.admission.call_count, 2)
        self.assertEqual(self.stopped.call_count, 2)
        self.assertEqual(self.receipt()['phase'], 'stopped_result')
        self.assertTrue(self.receipt()['all_vms_stopped'])
        self.assertEqual(self.receipt()['packet_sha256'], hashlib.sha256(b'synthetic trusted packet').hexdigest())
        self.assertEqual(self.receipt()['stdout_sha256'],
                         hashlib.sha256((self.work / 'stdout.json').read_bytes()).hexdigest())
        self.assertEqual(json.loads((self.work / 'stdout.json').read_bytes()), self.guest)
        self.assertEqual((self.work / 'stderr.log').read_bytes(), b'synthetic diagnostics')
        self.assert_restored()

    def test_duplicate_attempt_directory_never_resends(self):
        self.invoke()
        with self.assertRaises(FileExistsError):
            self.invoke()
        self.assertEqual(self.command.call_count, 1)
        self.assertEqual(self.stop.call_count, 1)
        self.assert_restored()

    def test_timeout_stops_records_and_retains_exclusive_reservation(self):
        self.command.side_effect = subprocess.TimeoutExpired('synthetic', 180)
        with self.assertRaises(subprocess.TimeoutExpired):
            self.invoke()
        self.assert_stopped_hold('TimeoutExpired')
        with self.assertRaises(FileExistsError):
            self.invoke()
        self.assertEqual(self.command.call_count, 1)

    def test_keyboard_interrupt_stops_and_restores_handlers(self):
        self.command.side_effect = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.invoke()
        self.assert_stopped_hold('KeyboardInterrupt')

    def test_invalid_json_stops_and_preserves_original_output(self):
        def malformed(argv, **kwargs):
            kwargs['stdout'].write(b'{broken')
            return SimpleNamespace(returncode=0)
        self.command.side_effect = malformed
        with self.assertRaises(ValueError):
            self.invoke()
        self.assert_stopped_hold('JSONDecodeError')
        self.assertEqual((self.work / 'stdout.json').read_bytes(), b'{broken')

    def test_cleanup_failure_never_returns_success(self):
        self.stop.side_effect = RuntimeError('synthetic stop failure')
        with self.assertRaises(RuntimeError):
            self.invoke()
        saved = self.receipt()
        self.assertEqual(saved['phase'], 'inspection_required')
        self.assertFalse(saved['all_vms_stopped'])
        self.assertEqual(saved['cleanup_error_type'], 'RuntimeError')
        self.assert_restored()

    def test_failed_post_stop_inventory_never_claims_all_stopped(self):
        self.stopped.side_effect = [None, RuntimeError('synthetic still running')]
        with self.assertRaises(RuntimeError):
            self.invoke()
        self.assertFalse(self.receipt()['all_vms_stopped'])
        self.assert_restored()

    def test_first_admission_failure_has_no_attempt_or_vm_command(self):
        self.admission.side_effect = RuntimeError('synthetic admission denied')
        with self.assertRaises(RuntimeError):
            self.invoke()
        self.command.assert_not_called()
        self.stop.assert_not_called()
        self.assertFalse(self.work.exists())
        self.assert_restored()

    def test_second_admission_failure_stops_and_retains_evidence(self):
        self.admission.side_effect = [None, RuntimeError('synthetic late STOP')]
        with self.assertRaises(RuntimeError):
            self.invoke()
        self.command.assert_not_called()
        self.assert_stopped_hold('RuntimeError')
        self.assertTrue((self.work / 'stdout.json').is_file())

    def test_missing_admission_rejected_before_any_vm_operation(self):
        with self.assertRaises(ValueError):
            self.invoke(admission=None)
        self.stopped.assert_not_called()
        self.command.assert_not_called()
        self.assertFalse(self.work.exists())

    def test_no_blanket_denial_prevents_reservation_and_execution(self):
        self.rules.return_value = []
        with self.assertRaises(RuntimeError):
            self.invoke()
        self.command.assert_not_called()
        self.assertFalse(self.work.exists())
        self.assert_restored()

    def test_guest_boundary_or_image_mismatch_cannot_return_success(self):
        original = copy.deepcopy(self.guest)
        changes = [dict(passed=False), dict(container_stopped=False), dict(image_id='wrong'),
                   dict(boundary={'observations_verified': True, 'full_isolation_accepted': True})]
        for index, change in enumerate(changes):
            with self.subTest(change=change):
                self.work = self.root / ('candidate-attempt-' + format(index, '032x'))
                self.guest = dict(original, **change)
                with self.assertRaises(RuntimeError):
                    self.invoke()
                self.assertEqual(self.receipt()['phase'], 'inspection_required')
                self.assertTrue(self.receipt()['all_vms_stopped'])
                self.assert_restored()


if __name__ == '__main__':
    unittest.main()
