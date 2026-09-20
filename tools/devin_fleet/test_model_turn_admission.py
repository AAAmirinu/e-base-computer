"""Frozen admission composition with private files and mocked live checks."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import uuid

import fleet
import model_turn_admission as policy
from sandbox_runtime import SandboxRuntime, ROLES
from sandbox_repository import GuestRepository


class ModelTurnAdmissionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.root = self.base / 'controller'
        self.root.mkdir(mode=0o700)
        self.run = self.root / 'turn'
        self.run.mkdir(mode=0o700)
        fences = self.root / 'model-turn-fences'
        fences.mkdir(mode=0o700)
        self.fence = fences / 'machine.json'
        self.registration = dict(schema=1, production_enabled=True, controller_root=str(self.root),
            migration_epoch='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', validation_image_id=policy.IMAGE,
            simultaneous_capacity_verified=1,
            roles={role: dict(name='e-base-' + role, id=str(uuid.UUID(int=i + 1)))
                   for i, role in enumerate(sorted(ROLES))})
        self.registry = self.base / 'sandbox-registry.json'
        self.write(self.registry, self.registration)
        self.reservation = dict(schema=1, operation_id='b' * 32, sequence=0, role='machine',
            migration_epoch=self.registration['migration_epoch'],
            sandbox_id=self.registration['roles']['machine']['id'], run_directory=str(self.run),
            state='unresolved', automatic_resume=False)
        self.write(self.fence, self.reservation)
        self.runtime = SandboxRuntime(self.registration, self.root, transport=Mock())
        self.runtime._entered = True
        self.entry = {'paths': ['src/**']}
        self.settings = {'turn_timeout_seconds': 30}
        self.boundary, self.network = Mock(return_value=None), Mock(return_value=None)
        self.patch('ROOT', self.base)
        self.patch('require_managed_namespace')
        self.lock = self.patch('global_lock_held', return_value=True)
        self.clock = self.patch('datetime')
        self.clock.now.return_value = datetime(2026, 9, 20, tzinfo=timezone.utc)
        self.catalog = self.patch('check_catalog', return_value={'catalog_verified': True})
        self.repo = self.new_lease()
        self.relative = '.fleet/control-' + 'c' * 32
        self.config = json.dumps(fleet.guest_permission_config(self.repo.guest_root, self.entry)).encode()
        self.prompt = b'synthetic prompt'
        self.prepared = dict(role='machine', relative=self.relative,
            config_sha256=hashlib.sha256(self.config).hexdigest(),
            prompt_sha256=hashlib.sha256(self.prompt).hexdigest())
        self.repo.read_bytes = Mock(side_effect=lambda path, **kw: self.config if path.endswith('config.json') else self.prompt)
        self.admit = self.make()

    def write(self, path, value):
        path.write_text(json.dumps(value))
        path.chmod(0o600)

    def patch(self, name, *args, **kwargs):
        context = patch.object(policy, name, *args, **kwargs)
        value = context.start()
        self.addCleanup(context.stop)
        return value

    def new_lease(self):
        controller = Mock()
        controller.fenced = False
        controller.sandbox_id = self.registration['roles']['machine']['id']
        self.runtime._active['machine'] = (Mock(), controller)
        return GuestRepository(controller, '/home/agent/workspace/machine', self.root / 'logs',
                               external_stop=self.runtime.stop_path)

    def make(self):
        return policy.make_admission(self.registration, 'machine', self.entry, self.settings,
                                     boundary_check=self.boundary, network_check=self.network)

    def call(self, stage, **overrides):
        args = dict(stage=stage, repo=None if stage == 'initial' else self.repo,
                    prepared=self.prepared if stage == 'before_model' else None, timeout=20)
        args.update(overrides)
        return self.admit(self.runtime, 'machine', self.settings, **args)

    def until_model(self):
        self.call('initial')
        self.call('before_prepare')

    def test_four_stages_use_same_active_model_lease_and_new_inspection_lease(self):
        self.until_model()
        result = self.call('before_model')
        self.catalog.assert_called_once()
        self.assertIs(self.catalog.call_args.args[0], self.repo)
        self.assertGreater(self.catalog.call_args.kwargs['timeout'], 0)
        self.assertLessEqual(self.catalog.call_args.kwargs['timeout'], 20)
        self.assertFalse(result['authentication_verified'])
        self.assertFalse(result['model_executed'])
        self.repo = self.new_lease()
        self.call('before_inspection')
        self.assertEqual(self.boundary.call_count, 4)
        self.assertEqual(self.network.call_count, 4)
        with self.assertRaises(RuntimeError):
            self.call('before_inspection')

    def test_order_failure_closes_callback_even_if_correct_stage_follows(self):
        with self.assertRaises(RuntimeError):
            self.call('before_model')
        with self.assertRaises(RuntimeError):
            self.call('initial')
        self.boundary.assert_not_called()

    def test_changed_registry_rejected_and_callback_cannot_resume(self):
        self.call('initial')
        self.write(self.registry, dict(self.registration, production_enabled=False))
        with self.assertRaises(ValueError):
            self.call('before_prepare')
        self.write(self.registry, self.registration)
        with self.assertRaises(RuntimeError):
            self.call('before_prepare')

    def test_explicit_registration_checker_replaces_only_disk_lookup(self):
        checker=Mock(return_value=None)
        with patch('prepared_candidate_trial_state.check_runtime_registration', checker), \
             patch('prepared_candidate_trial_state.trial_guest_root',
                   return_value='/home/agent/workspace/machine'):
            admit=policy.make_admission(self.registration,'machine',self.entry,self.settings,
                boundary_check=self.boundary,network_check=self.network,
                registration_check=checker)
            admit(self.runtime,'machine',self.settings,stage='initial',repo=None,
                  prepared=None,timeout=20)
        checker.assert_called_once_with(self.registration)
        with self.assertRaisesRegex(ValueError, 'fixed prepared-candidate'):
            policy.make_admission(self.registration,'machine',self.entry,self.settings,
                boundary_check=self.boundary,network_check=self.network,
                registration_check=lambda value: None)

    def test_same_identity_fence_bytes_change_rejected(self):
        self.call('initial')
        self.fence.write_text(json.dumps(self.reservation, indent=2))
        with self.assertRaises(ValueError):
            self.call('before_prepare')

    def test_observed_settings_change_rejected(self):
        self.settings['turn_timeout_seconds'] = 31
        with self.assertRaises(ValueError):
            self.call('initial')

    def test_unrelated_lease_rejected(self):
        self.call('initial')
        other = GuestRepository(Mock(), self.repo.guest_root, self.root / 'otherlogs',
                                external_stop=self.runtime.stop_path)
        with self.assertRaises(ValueError):
            self.call('before_prepare', repo=other)

    def test_policy_expansion_rejected_even_when_digest_matches(self):
        self.until_model()
        config = json.loads(self.config)
        config['permissions']['allow'].append('Write(/home/agent/workspace/machine/other/**)')
        self.config = json.dumps(config).encode()
        self.prepared['config_sha256'] = hashlib.sha256(self.config).hexdigest()
        with self.assertRaises(ValueError):
            self.call('before_model')
        self.catalog.assert_not_called()

    def test_prompt_digest_change_rejected_before_catalog(self):
        self.until_model()
        self.prompt = b'changed prompt'
        with self.assertRaises(ValueError):
            self.call('before_model')
        self.catalog.assert_not_called()

    def test_stop_or_expiry_blocks_before_live_checks(self):
        self.runtime.stop_path.touch()
        with self.assertRaises(RuntimeError):
            self.call('initial')
        self.boundary.assert_not_called()
        self.runtime.stop_path.unlink()
        self.admit = self.make()
        self.clock.now.return_value = policy.EXPIRY
        with self.assertRaises(RuntimeError):
            self.call('initial')
        self.boundary.assert_not_called()

    def test_callback_failure_cannot_be_retried(self):
        self.network.side_effect = RuntimeError('synthetic network uncertainty')
        with self.assertRaises(RuntimeError):
            self.call('initial')
        self.network.side_effect = None
        with self.assertRaises(RuntimeError):
            self.call('initial')
        self.assertEqual(self.network.call_count, 1)

    def test_lock_not_held_rejected_before_boundary_check(self):
        self.lock.return_value = False
        with self.assertRaises(ValueError):
            self.call('initial')
        self.boundary.assert_not_called()

    def test_boolean_verifier_result_is_rejected_and_callback_closed(self):
        for check in (self.boundary, self.network):
            for value in (False, True):
                with self.subTest(check=check is self.boundary, value=value):
                    self.boundary.return_value = None
                    self.network.return_value = None
                    self.admit = self.make()
                    check.return_value = value
                    with self.assertRaises((ValueError, RuntimeError)):
                        self.call('initial')
                    check.return_value = None
                    with self.assertRaises(RuntimeError):
                        self.call('initial')

    def test_frozen_entry_and_registration_do_not_expand_with_caller_mutation(self):
        self.entry['paths'].append('other/**')
        self.registration['roles']['machine']['name'] = 'changed'
        self.until_model()
        self.call('before_model')
        self.catalog.assert_called_once()

    def test_missing_boundary_or_network_callback_rejected(self):
        for checks in ({'boundary_check': None, 'network_check': self.network},
                       {'boundary_check': self.boundary, 'network_check': None}):
            with self.subTest(checks=checks), self.assertRaises(ValueError):
                policy.make_admission(self.registration, 'machine', self.entry, self.settings, **checks)


if __name__ == '__main__':
    unittest.main()
