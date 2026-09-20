"""Offline adapter contract tests; the real dispatcher is never invoked."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import sandbox_validation_adapter as adapter
import test_turn_validation_result as fixtures


class ValidationAdapterTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.snapshot = self.root / 'cycle' / 'model' / 'source-snapshot'
        self.capture = self.snapshot.parent / 'capture.json'
        self.turn = self.snapshot.parent / 'turn.json'
        self.output = self.root / ('dispatch-' + '1' * 32)
        self.fixture = fixtures.TurnValidationResultTests()
        self.fixture.setUp()
        self.fixture.image = adapter.dispatcher.IMAGE
        self.fixture.validator = adapter.dispatcher.UUID
        self.fixture.receipt['image_id'] = self.fixture.image
        self.fixture.dispatch.update(image_id=self.fixture.image, sandbox_id=self.fixture.validator)
        self.registration = dict(production_enabled=True, validation_image_id=self.fixture.image,
            migration_epoch=self.fixture.binding['migration_epoch'], roles={'machine': {'id': 'role-vm'}})
        self.disk = copy.deepcopy(self.registration)
        self.patch(adapter, 'ROOT', self.root)
        self.guard = self.patch(adapter, 'require_managed_namespace')
        self.reader = self.patch(adapter, '_file', side_effect=self.read)
        self.patch(adapter, 'load_snapshot', return_value=(b'manifest', {}, {'files': []}))
        self.patch(adapter, 'load_capture', return_value={'capture': {}})
        self.patch(adapter, 'load_turn_binding', return_value=self.fixture.binding)
        self.main = self.patch(adapter.dispatcher, 'main', side_effect=self.dispatch)

    def patch(self, owner, name, *args, **kwargs):
        context = patch.object(owner, name, *args, **kwargs)
        result = context.start()
        self.addCleanup(context.stop)
        return result

    def read(self, path, limit):
        path = Path(path)
        if path == self.root / 'sandbox-registry.json':
            return json.dumps(self.disk).encode()
        if path == self.turn:
            return json.dumps({'snapshot': {'manifest_sha256': self.fixture.binding['manifest_sha256']}}).encode()
        receipt, stdout = self.fixture.encoded()
        if path == self.output / 'dispatch.json':
            return json.dumps(receipt).encode()
        if path == self.output / 'stdout.log':
            return stdout
        raise AssertionError('Unexpected evidence read')

    def dispatch(self, argv, *, observer, expected_registration):
        observer(self.output)

    def invoke(self, **overrides):
        args = dict(snapshot_directory=self.snapshot, capture_path=self.capture,
                    turn_path=self.turn, registration=self.registration)
        args.update(overrides)
        return adapter.validate(**args)

    def test_success_returns_raw_evidence_and_bound_explicit_arguments(self):
        result = self.invoke()
        self.guard.assert_called_once_with()
        self.assertEqual(set(result), {'dispatch_raw', 'stdout_raw', 'validator_id', 'image_id'})
        self.assertEqual(result['validator_id'], adapter.dispatcher.UUID)
        self.assertEqual(result['image_id'], adapter.dispatcher.IMAGE)
        self.assertEqual(result['stdout_raw'], self.fixture.encoded()[1])
        self.assertEqual(self.main.call_args.kwargs['expected_registration'], self.registration)
        self.assertEqual(self.main.call_args.args[0], [
            '--snapshot', str(self.snapshot), '--manifest-sha256', self.fixture.binding['manifest_sha256'],
            '--capture-receipt', str(self.capture), '--turn-receipt', str(self.turn)])

    def test_git_image_uses_registered_flag_not_maintenance_flag(self):
        self.registration['validation_image_id'] = adapter.GIT_IMAGE
        self.disk = copy.deepcopy(self.registration)
        self.fixture.receipt['image_id'] = adapter.GIT_IMAGE
        self.fixture.dispatch['image_id'] = adapter.GIT_IMAGE
        result = self.invoke()
        arguments = self.main.call_args.args[0]
        self.assertIn('--registered-git-image', arguments)
        self.assertNotIn('--git-image-candidate', arguments)
        self.assertEqual(result['image_id'], adapter.GIT_IMAGE)

    def test_consistent_failure_returns_raw_evidence_even_after_dispatch_exception(self):
        self.fixture.receipt['test']['returncode'] = 1
        self.fixture.receipt['test_command_succeeded'] = False
        self.fixture.dispatch.update(returncode=1, phase='inspection_required')
        def failed(argv, *, observer, expected_registration):
            observer(self.output)
            raise RuntimeError('synthetic test failure')
        self.main.side_effect = failed
        result = self.invoke()
        self.assertEqual(json.loads(result['dispatch_raw'])['returncode'], 1)

    def test_registry_change_or_production_disabled_prevents_dispatch(self):
        original = copy.deepcopy(self.disk)
        for changed in (dict(original, migration_epoch='changed'), dict(original, production_enabled=False)):
            with self.subTest(changed=changed):
                self.disk = changed
                with self.assertRaises(ValueError):
                    self.invoke()
        self.main.assert_not_called()

    def test_unsupported_image_prevents_dispatch(self):
        self.registration['validation_image_id'] = 'sha256:' + '0' * 64
        self.disk = copy.deepcopy(self.registration)
        with self.assertRaises(ValueError):
            self.invoke()
        self.main.assert_not_called()

    def test_outside_snapshot_prevents_dispatch(self):
        with self.assertRaises(ValueError):
            self.invoke(snapshot_directory=self.root.parent / 'outside-snapshot')
        self.main.assert_not_called()

    def test_missing_or_duplicate_observation_rejected(self):
        for count in (0, 2):
            with self.subTest(count=count):
                def observe(argv, *, observer, expected_registration):
                    for _ in range(count):
                        observer(self.output)
                self.main.side_effect = observe
                with self.assertRaisesRegex(RuntimeError, 'unique completed dispatch'):
                    self.invoke()

    def test_unexpected_evidence_directory_rejected(self):
        for directory in (self.root / 'wrong-name', self.root / 'nested' / self.output.name,
                          self.root.parent / self.output.name):
            with self.subTest(directory=directory):
                self.main.side_effect = lambda argv, observer, expected_registration: observer(directory)
                with self.assertRaises(ValueError):
                    self.invoke()

    def test_stop_failure_not_accepted_as_completed_result(self):
        self.fixture.dispatch['validation_vm_stopped'] = False
        with self.assertRaises(ValueError):
            self.invoke()

    def test_exception_with_success_receipt_is_not_success(self):
        def failed(argv, *, observer, expected_registration):
            observer(self.output)
            raise RuntimeError('synthetic failure after output')
        self.main.side_effect = failed
        with self.assertRaisesRegex(RuntimeError, 'contradicts result'):
            self.invoke()

    def test_exception_without_observer_does_not_return_evidence(self):
        self.main.side_effect = RuntimeError('synthetic early failure')
        with self.assertRaisesRegex(RuntimeError, 'unique completed dispatch'):
            self.invoke()

    def test_namespace_rejection_precedes_disk_and_dispatch(self):
        self.guard.side_effect = RuntimeError('wrong namespace')
        with self.assertRaises(RuntimeError):
            self.invoke()
        self.reader.assert_not_called()
        self.main.assert_not_called()


if __name__ == '__main__':
    unittest.main()
