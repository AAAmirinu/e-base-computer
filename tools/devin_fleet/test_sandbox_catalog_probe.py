"""Catalog transport mocks; no CLI, model, authentication, or VM execution."""
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import sandbox_catalog_probe as probe
from sandbox_repository import GuestRepository


class SandboxCatalogProbeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.policy = self.root / 'model_catalog_policy.py'
        self.policy.write_text('# inert trusted policy fixture\n')
        self.controller = Mock()
        self.repo = GuestRepository(self.controller, '/home/agent/workspace/machine',
                                    self.root / 'logs', external_stop=self.root / 'STOP')
        self.result = dict(catalog_verified=True, model_uid='swe-2-high', cost_tier='Free',
                           catalog_sha256='a' * 64, model_executed=False, authentication_verified=False)
        self.returncode = 0
        self.log_mode = 'single'
        self.controller.execute.side_effect = self.execute
        self.patch('ROOT', self.root)
        self.guard = self.patch('require_managed_namespace')
        self.clock = self.patch('datetime')
        self.clock.now.return_value = datetime(2026, 9, 20, tzinfo=timezone.utc)

    def patch(self, name, *args, **kwargs):
        context = patch.object(probe, name, *args, **kwargs)
        result = context.start()
        self.addCleanup(context.stop)
        return result

    def execute(self, argv, **kwargs):
        self.assertEqual(argv[:4], ['python3', '-I', '-c', probe.PROBE])
        self.assertEqual(argv[4], self.policy.read_text())
        marker = argv[5]
        line = marker + json.dumps(self.result) + '\n'
        if self.log_mode == 'duplicate':
            line += line
        elif self.log_mode == 'missing':
            line = 'unrelated harmless status\n'
        elif self.log_mode == 'duplicate_key':
            line = marker + '{"catalog_verified":false,' + json.dumps(self.result)[1:] + '\n'
        log = kwargs['log_path']
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(line)
        return SimpleNamespace(returncode=self.returncode)

    def invoke(self, timeout=30):
        return probe.check_catalog(self.repo, timeout=timeout)

    def test_success_uses_same_lease_and_returns_no_authentication_claim(self):
        result = self.invoke()
        self.assertEqual(result, self.result)
        self.assertIs(result['model_executed'], False)
        self.assertIs(result['authentication_verified'], False)
        self.controller.execute.assert_called_once()
        kwargs = self.controller.execute.call_args.kwargs
        self.assertEqual(kwargs['cwd'], '/')
        self.assertEqual(kwargs['timeout'], 30)
        self.assertEqual(float(self.controller.execute.call_args.args[0][6]), 15)
        self.assertEqual(kwargs['max_log_bytes'], 65536)
        self.assertEqual(kwargs['external_stop'], self.repo.external_stop)
        self.controller.stop.assert_not_called()

    def test_timeout_is_capped_at_sixty_seconds_with_cleanup_grace(self):
        self.invoke(timeout=99)
        self.assertEqual(self.controller.execute.call_args.kwargs['timeout'], 75)
        self.assertEqual(float(self.controller.execute.call_args.args[0][6]), 60)

    def test_nonzero_outer_command_returncode_stops_lease(self):
        self.returncode = 1
        with self.assertRaises(ValueError):
            self.invoke()
        self.controller.stop.assert_called_once()

    def test_wrong_model_or_tier_and_unverified_catalog_rejected(self):
        original = dict(self.result)
        for key, value in (('model_uid', 'other'), ('cost_tier', 'Paid'),
                           ('catalog_verified', False), ('model_executed', True),
                           ('authentication_verified', True), ('catalog_sha256', 'bad')):
            with self.subTest(key=key):
                self.controller.stop.reset_mock()
                self.result = dict(original, **{key: value})
                with self.assertRaises(ValueError):
                    self.invoke()
                self.controller.stop.assert_called_once()

    def test_extra_secret_field_rejected_without_exception_leak(self):
        self.result['private'] = 'SYNTHETIC_SECRET'
        with self.assertRaises(ValueError) as caught:
            self.invoke()
        self.assertNotIn('SYNTHETIC_SECRET', str(caught.exception))
        self.controller.stop.assert_called_once()

    def test_missing_duplicate_or_duplicate_key_log_rejected(self):
        for mode in ('missing', 'duplicate', 'duplicate_key'):
            with self.subTest(mode=mode):
                self.controller.stop.reset_mock()
                self.log_mode = mode
                with self.assertRaises(ValueError):
                    self.invoke()
                self.controller.stop.assert_called_once()

    def test_expiry_before_probe_does_not_start_command(self):
        self.clock.now.return_value = probe.EXPIRY
        with self.assertRaises(RuntimeError):
            self.invoke()
        self.controller.execute.assert_not_called()

    def test_expiry_during_probe_rejects_result_and_stops(self):
        self.clock.now.side_effect = [datetime(2026, 10, 9, 23, 59, 59, tzinfo=timezone.utc), probe.EXPIRY]
        with self.assertRaises(RuntimeError):
            self.invoke()
        self.controller.execute.assert_not_called()
        self.controller.stop.assert_not_called()

    def test_transport_failure_stops_without_retry(self):
        self.controller.execute.side_effect = TimeoutError('synthetic transport timeout')
        with self.assertRaises(TimeoutError):
            self.invoke()
        self.controller.execute.assert_called_once()
        self.controller.stop.assert_called_once()

    def test_invalid_remaining_time_rejected_before_execution(self):
        for timeout in (0, -1, True, '20', float('nan'), float('inf')):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                self.invoke(timeout)
        self.controller.execute.assert_not_called()

    def test_non_guest_repository_has_no_host_fallback(self):
        with self.assertRaises(ValueError):
            probe.check_catalog(self.root, timeout=12)
        self.controller.execute.assert_not_called()


if __name__ == '__main__':
    unittest.main()
