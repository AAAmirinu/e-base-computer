"""Mock-only capacity preflight checks; no subprocess, VM, or model execution."""
from contextlib import ExitStack
from copy import deepcopy
import json
import os
import unittest
from unittest.mock import call, mock_open, patch

if os.name == 'posix':
    import sandbox_capacity_probe as probe


@unittest.skipUnless(os.name == 'posix', 'Dedicated Linux controller')
class CapacityProbeTests(unittest.TestCase):
    def setUp(self):
        roles = ('machine', 'coordinator', 'toolchain', 'kernel', 'stdlib',
                 'storage', 'services', 'applications', 'devtools', 'assurance')
        self.registration = {'roles': {
            role: {'name': 'e-base-'+role, 'id': str(index)}
            for index, role in enumerate(roles)}}
        self.rows = [dict(entry, status='stopped')
                     for entry in self.registration['roles'].values()]
        self.rows.append({'name': 'e-base-validation',
                          'id': '84a0fc99-4cbb-4383-a1df-4c22bbe0d2e6', 'status': 'stopped'})

    def inventory(self, rows, running=()):
        with patch.object(probe, 'run', return_value=json.dumps({'sandboxes': rows})) as run:
            probe.inventory(self.registration, running)
        run.assert_called_once_with('ls', '--json')

    def test_exact_registered_inventory_and_running_set(self):
        self.inventory(self.rows)
        self.rows[0]['status'] = 'running'
        self.rows[1]['status'] = 'running'
        self.inventory(self.rows, ('machine', 'coordinator'))

    def test_replaced_or_duplicate_registered_identity_refused(self):
        replaced = deepcopy(self.rows)
        replaced[0]['id'] = 'replacement'
        duplicate = deepcopy(self.rows)
        duplicate[-1] = deepcopy(duplicate[0])
        for rows in (replaced, duplicate):
            with self.subTest(rows=rows), self.assertRaises(RuntimeError):
                self.inventory(rows)

    def test_unexpected_running_role_or_validation_refused(self):
        for index in (0, 5, 10):
            rows = deepcopy(self.rows)
            rows[index]['status'] = 'running'
            with self.subTest(index=index), self.assertRaises(RuntimeError):
                self.inventory(rows)

    def test_expected_running_role_must_really_be_running(self):
        with self.assertRaises(RuntimeError):
            self.inventory(self.rows, ('machine',))

    def test_replaced_or_renamed_validation_vm_refused(self):
        for field in ('id', 'name'):
            rows = deepcopy(self.rows)
            rows[-1][field] = 'replacement'
            with self.subTest(field=field), self.assertRaisesRegex(RuntimeError, 'validation VM'):
                self.inventory(rows)

    def test_inventory_count_refused(self):
        for rows in (self.rows[:-1], self.rows+[deepcopy(self.rows[-1])]):
            with self.subTest(count=len(rows)), self.assertRaises(RuntimeError):
                self.inventory(rows)

    def preflight(self, available, rules):
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(probe, 'require_managed_namespace'))
        stack.enter_context(patch.object(probe.signal, 'signal'))
        stack.enter_context(patch.object(probe.Path, 'read_text', return_value=json.dumps(self.registration)))
        stack.enter_context(patch.object(probe, 'SandboxRuntime'))
        stack.enter_context(patch('builtins.open', mock_open()))
        stack.enter_context(patch.object(probe.fcntl, 'flock'))
        stack.enter_context(patch.object(probe, 'inventory'))
        stack.enter_context(patch.object(probe, 'available_kib', return_value=available))
        run = stack.enter_context(patch.object(probe, 'run', return_value=json.dumps({'rules': rules})))
        create = stack.enter_context(patch.object(probe.tempfile, 'mkdtemp'))
        write = stack.enter_context(patch.object(probe, 'atomic_write_json'))
        return run, create, write

    def test_low_memory_does_not_start_vm_or_create_receipt(self):
        run, create, write = self.preflight(10 * 1024 * 1024 - 1, [])
        with self.assertRaisesRegex(RuntimeError, 'Less than 10 GiB'):
            probe.main()
        run.assert_not_called()
        create.assert_not_called()
        write.assert_not_called()

    def test_missing_network_denial_does_not_execute_or_write(self):
        run, create, write = self.preflight(12 * 1024 * 1024, [])
        with self.assertRaisesRegex(RuntimeError, 'Network denial required'):
            probe.main()
        run.assert_called_once_with('policy', 'ls', 'e-base-machine', '--json')
        create.assert_not_called()
        write.assert_not_called()

    def test_second_exec_failure_stops_attempted_roles_in_reverse(self):
        run, create, write = self.preflight(12 * 1024 * 1024, [])
        create.return_value = '/home/fleet/controller-validation/capacity-probe-mock'
        receipts = []
        write.side_effect = lambda path, record: receipts.append(deepcopy(record))
        def result(*args, **kwargs):
            if args[0] == 'policy':
                return json.dumps({'rules': [{'scope': 'sandbox:'+args[2],
                    'resource_type': 'network', 'decision': 'deny', 'status': 'active',
                    'resources': ['**']}]})
            if args[:2] == ('exec', 'e-base-coordinator'):
                raise RuntimeError('second exec failed')
            return ''
        run.side_effect = result
        with patch('builtins.print'), self.assertRaisesRegex(RuntimeError, 'second exec failed'):
            probe.main()
        self.assertEqual(run.call_args_list[-2:], [
            call('stop', 'e-base-coordinator'), call('stop', 'e-base-machine')])
        self.assertEqual([c for c in run.call_args_list if c.args[0] == 'exec'], [
            call('exec', 'e-base-machine', '/usr/bin/true', timeout=45),
            call('exec', 'e-base-coordinator', '/usr/bin/true', timeout=45)])
        self.assertTrue(receipts[-1]['all_vms_stopped'])
        self.assertEqual(receipts[-1]['cleanup_errors'], [])
        self.assertTrue(all(r['production_capacity_promoted'] is False for r in receipts))
        self.assertNotIn('simultaneous_idle_vms', receipts[-1])

    def ten_preflight(self):
        run, create, write = self.preflight(12 * 1024 * 1024, [])
        create.return_value = '/home/fleet/controller-validation/capacity-probe-mock'
        receipts = []
        write.side_effect = lambda path, record: receipts.append(deepcopy(record))
        def result(*args, **kwargs):
            if args[0] == 'policy':
                return json.dumps({'rules': [{'scope': 'sandbox:'+args[2],
                    'resource_type': 'network', 'decision': 'deny', 'status': 'active',
                    'resources': ['**']}]})
            return ''
        run.side_effect = result
        return run, create, write, receipts

    def test_ten_mode_checks_all_policies_before_first_exec(self):
        run, create, write, receipts = self.ten_preflight()
        normal_result = run.side_effect
        def missing_last_policy(*args, **kwargs):
            if args[:3] == ('policy', 'ls', 'e-base-assurance'):
                return json.dumps({'rules': []})
            return normal_result(*args, **kwargs)
        run.side_effect = missing_last_policy
        with self.assertRaisesRegex(RuntimeError, 'Network denial required'):
            probe.main(ten=True)
        self.assertEqual(run.call_args_list, [
            call('policy', 'ls', 'e-base-'+role, '--json') for role in probe.TEN_TARGETS])
        self.assertEqual(len(run.call_args_list), 10)
        create.assert_not_called()
        write.assert_not_called()

    def test_ten_idle_success_stops_reverse_without_promoting_capacity(self):
        run, create, write, receipts = self.ten_preflight()
        with patch('builtins.print'):
            probe.main(ten=True)
        self.assertEqual(run.call_args_list[:10], [
            call('policy', 'ls', 'e-base-'+role, '--json') for role in probe.TEN_TARGETS])
        self.assertEqual(run.call_args_list[10:20], [
            call('exec', 'e-base-'+role, '/usr/bin/true', timeout=45)
            for role in probe.TEN_TARGETS])
        self.assertEqual(run.call_args_list[20:], [
            call('stop', 'e-base-'+role) for role in reversed(probe.TEN_TARGETS)])
        self.assertEqual(receipts[-1]['phase'], 'ten_idle_vms_verified')
        self.assertEqual(receipts[-1]['simultaneous_idle_vms'], 10)
        self.assertEqual([s['running_count'] for s in receipts[-1]['stages']], list(range(1, 11)))
        self.assertTrue(receipts[-1]['all_vms_stopped'])
        self.assertEqual(receipts[-1]['cleanup_errors'], [])
        for receipt in receipts:
            for flag in ('production_capacity_promoted', 'model_executed', 'source_executed'):
                self.assertIs(receipt[flag], False)

    def test_ten_headroom_drop_after_two_stops_started_without_success(self):
        run, create, write, receipts = self.ten_preflight()
        high, low = 12 * 1024 * 1024, 6 * 1024 * 1024 - 1
        # Initial, before/after first, before/after second, before third, cleanup.
        with patch.object(probe, 'available_kib', side_effect=[high]*5+[low, high]), \
                patch('builtins.print'), \
                self.assertRaisesRegex(RuntimeError, 'Memory headroom fell below reserve'):
            probe.main(ten=True)
        self.assertEqual([c for c in run.call_args_list if c.args[0] == 'exec'], [
            call('exec', 'e-base-machine', '/usr/bin/true', timeout=45),
            call('exec', 'e-base-coordinator', '/usr/bin/true', timeout=45)])
        self.assertEqual(run.call_args_list[-2:], [
            call('stop', 'e-base-coordinator'), call('stop', 'e-base-machine')])
        self.assertEqual(receipts[-1]['phase'], 'prepared')
        self.assertNotIn('simultaneous_idle_vms', receipts[-1])
        self.assertEqual(len(receipts[-1]['stages']), 2)
        self.assertTrue(receipts[-1]['all_vms_stopped'])
        self.assertEqual(receipts[-1]['cleanup_errors'], [])
        self.assertTrue(all(r['production_capacity_promoted'] is False for r in receipts))


if __name__ == '__main__':
    unittest.main()
