"""Offline tests for the fixed prepared-candidate validation adapter."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import prepared_trial_validation_adapter as adapter
import test_turn_validation_result as fixtures


class PreparedTrialValidationAdapterTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.controller = self.root / 'production-registration-trial-v1' / 'controller'
        self.snapshot = self.controller / 'cycles' / 'cycle' / 'model' / 'source-snapshot'
        self.capture = self.snapshot.parent / 'capture.json'
        self.turn = self.snapshot.parent / 'turn.json'
        self.output = self.root / ('dispatch-' + '1' * 32)
        self.fixture = fixtures.TurnValidationResultTests()
        self.fixture.setUp()
        self.fixture.image = adapter.GIT_IMAGE
        self.fixture.validator = adapter.dispatcher.UUID
        self.fixture.receipt['image_id'] = adapter.GIT_IMAGE
        self.fixture.dispatch.update(image_id=adapter.GIT_IMAGE,
                                     sandbox_id=adapter.dispatcher.UUID)
        self.registration = dict(production_enabled=True,
            validation_image_id=adapter.GIT_IMAGE,
            migration_epoch=self.fixture.binding['migration_epoch'],
            controller_root=str(self.controller), roles={'machine': {'id': 'role-vm'}})
        self.patch(adapter.trial_state, 'CONTROLLER', self.controller)
        self.patch(adapter, 'EVIDENCE_ROOT', self.root)
        self.guard = self.patch(adapter, 'require_managed_namespace')
        self.check = self.patch(adapter.trial_state, 'check_runtime_registration')
        self.runtime = self.patch(adapter.trial_state, 'runtime_registration',
                                  return_value=copy.deepcopy(self.registration))
        self.reader = self.patch(adapter, '_file', side_effect=self.read)
        self.patch(adapter, 'load_snapshot', return_value=(b'manifest', {}, {'files': []}))
        self.patch(adapter, 'load_capture', return_value={'capture': {}})
        self.patch(adapter, 'load_turn_binding', return_value=self.fixture.binding)
        self.dispatcher_main = adapter.dispatcher.main
        self.main = self.patch(adapter.dispatcher, 'main', side_effect=self.dispatch)

    def patch(self, owner, name, *args, **kwargs):
        context = patch.object(owner, name, *args, **kwargs)
        result = context.start()
        self.addCleanup(context.stop)
        return result

    def read(self, path, limit):
        path = Path(path)
        if path == self.turn:
            return json.dumps({'snapshot': {'manifest_sha256':
                self.fixture.binding['manifest_sha256']}}).encode()
        receipt, stdout = self.fixture.encoded()
        if path == self.output / 'dispatch.json':
            return json.dumps(receipt).encode()
        if path == self.output / 'stdout.log':
            return stdout
        raise AssertionError('Unexpected evidence read')

    def dispatch(self, argv, **kwargs):
        kwargs['observer'](self.output)

    def invoke(self, **overrides):
        values = dict(snapshot_directory=self.snapshot, capture_path=self.capture,
                      turn_path=self.turn, registration=self.registration)
        values.update(overrides)
        return adapter.validate(**values)

    def test_exact_trial_uses_only_dedicated_dispatch_arguments(self):
        result = self.invoke()
        self.assertEqual(result['image_id'], adapter.GIT_IMAGE)
        self.check.assert_called_once_with(self.registration)
        kwargs = self.main.call_args.kwargs
        self.assertIs(kwargs['prepared_trial_check'],
                      adapter.trial_state.check_runtime_registration)
        self.assertIs(kwargs['prepared_trial_registration'], self.registration)
        self.assertIs(kwargs['prepared_trial_test'], True)
        self.assertNotIn('expected_registration', kwargs)
        self.assertIn('--registered-git-image', self.main.call_args.args[0])

    def test_registration_drift_stops_before_dispatch(self):
        self.runtime.return_value = dict(self.registration, migration_epoch='changed')
        with self.assertRaises(ValueError):
            self.invoke()
        self.main.assert_not_called()

    def test_wrong_image_or_outside_snapshot_stops_before_dispatch(self):
        changed = dict(self.registration, validation_image_id='sha256:' + '0' * 64)
        self.runtime.return_value = copy.deepcopy(changed)
        with self.assertRaises(ValueError):
            self.invoke(registration=changed)
        self.main.assert_not_called()
        self.runtime.return_value = copy.deepcopy(self.registration)
        with self.assertRaises(ValueError):
            self.invoke(snapshot_directory=self.root / 'outside')
        self.main.assert_not_called()

    def test_dispatcher_rejects_any_generic_or_mismatched_checker(self):
        original = adapter.trial_state.check_runtime_registration
        with self.assertRaisesRegex(ValueError, 'Exact prepared trial'):
            self.dispatcher_main([], prepared_trial_registration=self.registration,
                                 prepared_trial_check=lambda value: None)
        with self.assertRaisesRegex(ValueError, 'Exact prepared trial'):
            self.dispatcher_main([], prepared_trial_check=original)
        with self.assertRaisesRegex(ValueError, 'Exact prepared trial'):
            self.dispatcher_main([], prepared_trial_registration=self.registration,
                prepared_trial_check=original, expected_registration=self.registration)

    def test_dispatcher_trial_cannot_select_legacy_or_maintenance_image(self):
        required = ['--snapshot', str(self.snapshot), '--manifest-sha256', '0' * 64]
        for arguments in (required, required + ['--git-image-candidate']):
            with self.subTest(arguments=arguments), self.assertRaisesRegex(
                    ValueError, 'registered Git image'):
                self.dispatcher_main(arguments,
                    prepared_trial_registration=self.registration,
                    prepared_trial_check=adapter.trial_state.check_runtime_registration)

    def test_fixed_trial_test_selector_requires_exact_identity_and_boolean(self):
        with self.assertRaisesRegex(ValueError, 'exact prepared trial identity'):
            self.dispatcher_main([], prepared_trial_test=True)
        with self.assertRaisesRegex(TypeError, 'selector must be boolean'):
            self.dispatcher_main([], prepared_trial_test=1)


if __name__ == '__main__':
    unittest.main()
