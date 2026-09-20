"""Stateful policy simulation only; never changes real VM or network state."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import model_network_window as window
import model_network_admission as network
from sandbox_repository import GuestRepository
from test_model_network_admission import rules


class ModelNetworkWindowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.run = self.root / 'turn'
        self.run.mkdir(mode=0o700)
        self.directory = self.run / 'network-window'
        self.rows = rules()
        self.counter = 0
        self.failure = None
        self.events = []
        self.controller = Mock()
        self.controller.fenced = False
        self.controller.sandbox_id = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
        self.runtime = SimpleNamespace(root=self.root, stop_path=self.root / 'STOP', _entered=True,
            _failed=False, _active={'machine': (Mock(), self.controller)},
            registration={'production_enabled': True, 'controller_root': str(self.root),
                          'migration_epoch': 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
                          'roles': {'machine': {'name': 'e-base-machine', 'id': self.controller.sandbox_id}}},
            transport=SimpleNamespace(control=Mock(side_effect=self.transport)))
        fences = self.root / 'model-turn-fences'
        fences.mkdir(mode=0o700)
        self.fence = fences / 'machine.json'
        self.reservation = dict(schema=1, role='machine', sandbox_id=self.controller.sandbox_id,
            migration_epoch=self.runtime.registration['migration_epoch'], operation_id='c' * 32,
            sequence=0, run_directory=str(self.run), state='unresolved', automatic_resume=False)
        self.write_fence()
        self.repo = GuestRepository(self.controller, '/home/agent/workspace/machine',
                                    self.root / 'logs', external_stop=self.runtime.stop_path)
        for name, value in (('require_managed_namespace', None), ('global_lock_held', True)):
            context = patch.object(window, name, return_value=value)
            context.start()
            self.addCleanup(context.stop)
        context = patch.object(network, 'require_managed_namespace')
        context.start()
        self.addCleanup(context.stop)

    def transport(self, argv, timeout):
        self.assertEqual(argv[:2], ['/usr/bin/sbx', 'policy'])
        self.assertGreater(timeout, 0)
        action = argv[2]
        self.events.append((action, argv[-1]))
        code = 0
        if action == 'ls':
            data = {'rules': copy.deepcopy(self.rows)}
        elif action == 'check':
            allow, deny = set(), set()
            for row in self.rows:
                (allow if row['decision'] == 'allow' else deny).update(row['resources'])
            permitted = argv[-1] in allow and argv[-1] not in deny and '**' not in deny
            data, code = {'allowed': permitted}, 0 if permitted else 1
        elif action == 'deny':
            resources = argv[-1].split(',')
            if self.failure=='deduplicated' and resources!=['**']:
                return SimpleNamespace(returncode=0,stdout='{}')
            if resources == ['**'] and self.failure == 'close':
                raise RuntimeError('synthetic close failure')
            self.counter += 1
            row = dict(self.rows[0], id='new-' + str(self.counter), editable=True,
                       decision='deny', resources=resources)
            self.rows.append(row)
            if resources != ['**']:
                if self.failure == 'add':
                    raise RuntimeError('synthetic uncertain add')
                if self.failure == 'unknown':
                    row['resources'].append('unknown.invalid:443')
                if self.failure == 'mutation':
                    self.rows[0]['extra'] = 'changed-vendor-metadata'
                if self.failure == 'missing-telemetry':
                    row['resources']=[h for h in resources if h not in network.DENY_ONLY_HOSTS]
            data = {}
        elif action == 'rm':
            self.assertEqual(self.receipt()['phase'], 'opening')
            self.assertIn(argv[-1], ('owned','feature'))
            self.rows = [row for row in self.rows if row['id'] != argv[-1]]
            if self.failure == 'remove':
                raise RuntimeError('synthetic uncertain remove')
            data = {}
        else:
            raise AssertionError('Unexpected mutating action')
        return SimpleNamespace(returncode=code, stdout=json.dumps(data))

    def write_fence(self):
        self.fence.write_text(json.dumps(self.reservation))
        self.fence.chmod(0o600)

    def enter(self, timeout=30):
        return window.model_network_window(self.runtime, 'machine', self.repo, self.directory, timeout=timeout)

    def receipt(self):
        return json.loads((self.directory / 'network-window.json').read_bytes())

    def assert_closed(self):
        record = self.receipt()
        self.assertEqual(record['phase'], 'closed')
        self.assertTrue(record['network_denied_after'])
        self.assertFalse(record['automatic_resume'])
        self.assertTrue(any(row['decision'] == 'deny' and row['resources'] == ['**'] for row in self.rows))

    def test_success_opens_only_model_hosts_then_closes_without_removing_created_denies(self):
        with self.enter():
            self.assertEqual(self.receipt()['phase'], 'open')
            self.assertFalse(any(row['resources'] == ['**'] for row in self.rows))
            restricted = set().union(*(set(row['resources']) for row in self.rows if row['decision'] == 'deny'))
            self.assertEqual(restricted, (window.KIT_HOSTS - window.MODEL_HOSTS)|window.DENY_ONLY_HOSTS)
        self.assert_closed()
        created = self.receipt()['created_deny_ids']
        self.assertTrue(created)
        self.assertTrue(set(created) <= {row['id'] for row in self.rows})
        self.assertEqual([event for event in self.events if event[0] == 'rm'], [('rm', 'owned')])
        self.controller.stop.assert_not_called()

    def test_nonproduction_still_refuses_before_mutation(self):
        self.runtime.registration['production_enabled']=False
        with self.assertRaises(ValueError),self.enter(): self.fail('Production gate bypassed')
        self.assertEqual(self.events,[])

    def test_catalog_feature_window_restores_individual_deny(self):
        self.runtime.registration['production_enabled']=False
        self.rows.append(dict(self.rows[1],id='feature',resources=[network.FEATURE_HOST]))
        with patch.object(window,'CATALOG_WINDOW',self.directory):
            with window._policy_window(self.runtime,'machine',self.repo,self.directory,timeout=60,catalog_access=True):
                network.check_network(self.runtime,'machine',stage='before_model',repo=self.repo,timeout=30,catalog_access=True)
                with self.assertRaises(ValueError):
                    network.check_network(self.runtime,'machine',stage='before_model',repo=self.repo,timeout=30)
        self.assert_closed()
        self.assertTrue(any(r['decision']=='deny' and r['resources']==[network.FEATURE_HOST] for r in self.rows))
        self.assertEqual([e for e in self.events if e[0]=='rm'],[('rm','feature'),('rm','owned')])

    def test_catalog_window_refuses_production(self):
        with patch.object(window,'CATALOG_WINDOW',self.directory),self.assertRaises(ValueError):
            with window._policy_window(self.runtime,'machine',self.repo,self.directory,timeout=60,catalog_access=True):
                self.fail('Production catalog override')
        self.assertEqual(self.events,[])

    def test_feature_access_refuses_unregistered_maintenance_window(self):
        self.runtime.registration['production_enabled']=False
        with self.assertRaisesRegex(ValueError,'Fixed nonproduction diagnostic'):
            with window._policy_window(self.runtime,'machine',self.repo,self.directory,timeout=60,catalog_access=True):
                self.fail('Unregistered maintenance window admitted')
        self.assertEqual(self.events,[])

    def test_mcp_feature_window_refuses_production(self):
        with patch.object(window,'MCP_WINDOW',self.directory),self.assertRaises(ValueError):
            with window._policy_window(self.runtime,'machine',self.repo,self.directory,timeout=60,catalog_access=True):
                self.fail('Production MCP override')
        self.assertEqual(self.events,[])

    def test_existing_complete_denials_do_not_require_new_duplicate_rows(self):
        self.rows.append(dict(self.rows[1],id='previous-restrictions',
            resources=sorted((network.KIT_HOSTS-network.MODEL_HOSTS)|network.DENY_ONLY_HOSTS)))
        self.failure='deduplicated'
        with self.enter(): self.assertEqual(self.receipt()['created_deny_ids'],[])
        self.assert_closed()

    def test_dedup_without_complete_existing_coverage_does_not_open(self):
        self.failure='deduplicated'
        with self.assertRaisesRegex(ValueError,'Exact new restrictions'),self.enter():
            self.fail('Incomplete existing denial')
        self.assertFalse(any(action=='rm' for action,_ in self.events))
        self.assert_closed()

    def test_uncertain_removal_still_restores_blanket_denial(self):
        self.failure = 'remove'
        with self.assertRaises(RuntimeError):
            with self.enter():
                self.fail('Body must not run after uncertain removal')
        self.assert_closed()

    def test_failed_add_does_not_remove_original_denial(self):
        self.failure = 'add'
        with self.assertRaises(RuntimeError):
            with self.enter():
                self.fail('Body must not run')
        self.assert_closed()
        self.assertFalse(any(action == 'rm' for action, _ in self.events))

    def test_missing_telemetry_restriction_keeps_original_blanket_denial(self):
        self.failure='missing-telemetry'
        with self.assertRaisesRegex(ValueError,'Exact new restrictions'),self.enter():
            self.fail('Incomplete denial must not open network')
        self.assertFalse(any(action=='rm' for action,_ in self.events))
        self.assert_closed()

    def test_unknown_created_endpoint_is_not_used_to_open_network(self):
        self.failure = 'unknown'
        with self.assertRaises(ValueError):
            with self.enter():
                self.fail('Body must not run')
        self.assertFalse(any(action == 'rm' for action, _ in self.events))
        self.assertEqual(self.receipt()['phase'], 'inspection_required')
        self.controller.stop.assert_called_once()

    def test_vendor_semantic_mutation_prevents_opening(self):
        self.failure = 'mutation'
        with self.assertRaises(ValueError):
            with self.enter():
                self.fail('Body must not run')
        self.assertFalse(any(action == 'rm' for action, _ in self.events))
        self.assert_closed()

    def test_body_exception_closes_without_automatic_retry(self):
        with self.assertRaisesRegex(RuntimeError, 'body'):
            with self.enter():
                raise RuntimeError('synthetic body failure')
        self.assert_closed()

    def test_close_failure_preserves_inspection_hold_and_stops_vm(self):
        with self.assertRaises(RuntimeError):
            with self.enter():
                self.failure = 'close'
        self.assertEqual(self.receipt()['phase'], 'inspection_required')
        self.assertFalse(self.receipt()['network_denied_after'])
        self.controller.stop.assert_called_once()

    def test_stop_before_open_still_allows_restrictive_cleanup(self):
        self.runtime.stop_path.touch()
        with self.assertRaises(RuntimeError):
            with self.enter():
                self.fail('STOP must block body')
        self.assert_closed()
        self.assertFalse(any(action == 'rm' for action, _ in self.events))

    def test_shared_deadline_does_not_cancel_cleanup(self):
        with patch.object(window.time, 'monotonic', side_effect=[0] + [100] * 200):
            with self.assertRaises(RuntimeError):
                with self.enter(timeout=1):
                    self.fail('Expired deadline must block body')
        self.assert_closed()

    def test_existing_directory_refuses_before_network_changes(self):
        self.directory.mkdir()
        with self.assertRaises(FileExistsError):
            with self.enter():
                self.fail('Existing reservation must block body')
        self.runtime.transport.control.assert_not_called()

    def test_window_path_must_be_exact_fenced_run_child(self):
        for directory in (self.root / 'network-window', self.run / 'other-window'):
            with self.subTest(directory=directory):
                self.directory = directory
                with self.assertRaises(ValueError):
                    with self.enter():
                        self.fail('Untracked journal path must be refused')
                self.assertFalse(directory.exists())
        self.runtime.transport.control.assert_not_called()

    def test_fence_role_epoch_or_vm_mismatch_prevents_policy_mutation(self):
        original = dict(self.reservation)
        for key, value in (('role', 'stdlib'),
                           ('migration_epoch', 'dddddddd-dddd-4ddd-8ddd-dddddddddddd'),
                           ('sandbox_id', 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee')):
            with self.subTest(key=key):
                self.reservation = dict(original, **{key: value})
                self.write_fence()
                with self.assertRaises(ValueError):
                    with self.enter():
                        self.fail('Foreign fence must be refused')
                self.assertFalse(self.directory.exists())
        self.runtime.transport.control.assert_not_called()

    def test_missing_or_partial_fence_prevents_policy_mutation(self):
        self.fence.unlink()
        with self.assertRaises(FileNotFoundError):
            with self.enter():
                self.fail('Missing fence must be refused')
        self.fence.write_bytes(b'{')
        with self.assertRaises(ValueError):
            with self.enter():
                self.fail('Partial fence must be refused')
        self.runtime.transport.control.assert_not_called()

    def test_fenced_run_outside_registered_root_refused(self):
        self.reservation['run_directory'] = str(self.root.parent / 'foreign-turn')
        self.write_fence()
        with self.assertRaises(ValueError):
            with self.enter():
                self.fail('Outside run must be refused')
        self.runtime.transport.control.assert_not_called()


if __name__ == '__main__':
    unittest.main()
