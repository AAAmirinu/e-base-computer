from pathlib import Path
import os
import tempfile
import unittest
import uuid
from unittest.mock import patch

from sandbox_control import SandboxError, SandboxFenced
from sandbox_runtime import SandboxRuntime, ROLES
from test_sandbox_control import FakeTransport


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.registration = {'schema': 1, 'simultaneous_capacity_verified': 1,
            'roles': {r: {'id': str(uuid.uuid4()), 'name': 'e-base-' + r} for r in ROLES}}
        self.transport = FakeTransport()
        self.transport.rows = [dict(v, status='stopped') for v in self.registration['roles'].values()]
        # Generic runtime tests must not depend on persistent fixed maintenance
        # reservations under /home/fleet/controller-validation. The dedicated
        # restart-guard test below installs its own rejecting side effect.
        maintenance = patch('mcp_maintenance_restart.require_closed_maintenance')
        maintenance.start()
        self.addCleanup(maintenance.stop)

    def runtime(self, **kwargs):
        return SandboxRuntime(self.registration, self.root, transport=self.transport, **kwargs)

    def test_role_binding_capacity_and_final_stop(self):
        with self.runtime() as runtime:
            with runtime.role('machine') as repo:
                self.assertEqual(repo.guest_root, '/home/agent/workspace/machine')
                self.assertEqual(repo.external_stop, self.root / 'STOP')
                with self.assertRaises(SandboxError), runtime.role('kernel'):
                    pass
            self.assertTrue(repo.controller.fenced)
        self.assertIn('stop', [e[0] for e in self.transport.events])

    def test_production_root_requires_trusted_registration_pin(self):
        self.registration['production_enabled'] = True
        with self.assertRaises(ValueError):
            self.runtime()
        self.registration['controller_root'] = str(self.root/'other')
        with self.assertRaises(ValueError):
            self.runtime()
        self.registration['controller_root'] = str(self.root)
        self.assertEqual(self.runtime().root, self.root)

    def test_production_restart_guard_failure_blocks_runtime_before_resume(self):
        self.registration.update(production_enabled=True,controller_root=str(self.root))
        with patch('network_restart_guard.require_closed_windows',side_effect=ValueError('uncertain window')):
            with self.assertRaisesRegex(ValueError,'uncertain window'), self.runtime():
                self.fail('Runtime admitted')
        self.assertFalse(any(e[0]=='spawn' for e in self.transport.events))

    def test_maintenance_restart_guard_blocks_nonproduction_before_resume(self):
        self.registration['production_enabled']=False
        with patch('mcp_maintenance_restart.require_closed_maintenance',side_effect=ValueError('maintenance uncertain')):
            with self.assertRaisesRegex(ValueError,'maintenance uncertain'),self.runtime():
                self.fail('Maintenance runtime admitted')
        self.assertFalse(any(e[0]=='spawn' for e in self.transport.events))

    def test_production_live_network_failure_blocks_role_before_resume(self):
        self.registration.update(production_enabled=True,controller_root=str(self.root))
        with patch('network_restart_guard.require_closed_windows'), patch(
                'model_network_admission.check_network',side_effect=ValueError('open policy')) as check:
            with self.runtime() as runtime:
                with self.assertRaisesRegex(ValueError,'open policy'), runtime.role('machine'):
                    self.fail('VM admitted')
                with self.assertRaises(SandboxError), runtime.role('machine'):
                    self.fail('Failed runtime reused')
        check.assert_called_once()
        self.assertFalse(any(e[0]=='spawn' for e in self.transport.events))

    def test_stale_handles_cannot_stop_new_lease(self):
        with self.runtime() as runtime:
            with runtime.role('machine') as old:
                pass
            with runtime.role('machine') as new:
                before = len(self.transport.events)
                for action in (lambda: old.git('status'), lambda: old.read_bytes('a'),
                               lambda: old.write_bytes('a', b'x')):
                    with self.assertRaises(SandboxFenced):
                        action()
                old.controller.stop()
                self.assertEqual(len(self.transport.events), before)
                self.assertFalse(new.controller.fenced)

    def test_stop_failure_poisons_runtime(self):
        with self.runtime() as runtime:
            with self.assertRaises(SandboxError):
                with runtime.role('machine'):
                    self.transport.fail_stop = True
            self.transport.fail_stop = False
            with self.assertRaises(SandboxError), runtime.role('kernel'):
                pass

    def test_global_stop_blocks_admission(self):
        (self.root / 'STOP').touch()
        with self.runtime() as runtime:
            with self.assertRaises(SandboxFenced), runtime.role('machine'):
                pass
        self.assertFalse(any(e[0] == 'spawn' for e in self.transport.events))

    def test_dangling_stop_entry_blocks_admission(self):
        with self.runtime() as runtime:
            with patch('sandbox_runtime.os.path.lexists', return_value=True):
                with self.assertRaises(SandboxFenced), runtime.role('machine'):
                    pass
        self.assertFalse(any(e[0] == 'spawn' for e in self.transport.events))

    @unittest.skipIf(os.name == 'nt', 'Dedicated Linux lock namespace')
    def test_linux_lock_ignores_temporary_environment(self):
        with patch.dict(os.environ, {'TMPDIR': '/untrusted/alternate'}):
            self.assertEqual(self.runtime()._lock.path, Path('/tmp/e-base-devin-fleet-global.lock'))

    def test_replaced_identity_refused_and_lock_released(self):
        self.transport.rows[0]['id'] = str(uuid.uuid4())
        with self.assertRaises(SandboxError), self.runtime():
            pass
        self.transport.rows = [dict(v, status='stopped') for v in self.registration['roles'].values()]
        with self.runtime():
            pass

    def test_unregistered_workload_blocks_entry_and_releases_lock(self):
        for name in ('e-base-validation', 'unexpected-workload'):
            for status in ('running', 'starting', 'unknown', None):
                with self.subTest(name=name, status=status):
                    extra = dict(name=name, id=str(uuid.uuid4()), status=status)
                    self.transport.rows.append(extra)
                    before = len(self.transport.events)
                    with self.assertRaises(SandboxError), self.runtime():
                        pass
                    events = self.transport.events[before:]
                    self.assertFalse(any(e[0] in ('spawn', 'stop') for e in events))
                    self.transport.rows.pop()
                    # A refusal must not leave the global lock held.
                    with self.runtime():
                        pass

    def test_stopped_validator_does_not_consume_model_role_capacity(self):
        self.transport.rows.append(dict(name='e-base-validation',
                                        id=str(uuid.uuid4()), status='stopped'))
        with self.runtime() as runtime:
            with runtime.role('machine') as repo:
                self.assertEqual(repo.guest_root, '/home/agent/workspace/machine')

    def test_unverified_capacity_and_duplicate_identity_rejected(self):
        with self.assertRaises(ValueError):
            self.runtime(capacity=2)
        self.registration['roles']['kernel']['id'] = self.registration['roles']['machine']['id']
        with self.assertRaises(ValueError):
            self.runtime()


if __name__ == '__main__':
    unittest.main()
