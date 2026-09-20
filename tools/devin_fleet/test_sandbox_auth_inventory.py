"""Mock-only offline auth inventory; no VM, credentials, or model access."""
from contextlib import ExitStack
from copy import deepcopy
import json
import os
from pathlib import Path
import unittest
from unittest.mock import call, mock_open, patch

if os.name == 'posix':
    import sandbox_auth_inventory as probe


@unittest.skipUnless(os.name == 'posix', 'Dedicated Linux controller')
class AuthInventoryTests(unittest.TestCase):
    def result(self, status='unclassified'):
        return {'status': status, 'returncode': 0,
                'raw_output_suppressed': True, 'model_executed': False}

    def test_only_expected_classifications_and_boolean_flags(self):
        for status in ('not_logged_in', 'unclassified', 'timeout'):
            value = self.result(status)
            self.assertEqual(probe.classification(json.dumps(value)), value)
        invalid = [dict(self.result(), status='authenticated'),
                   dict(self.result(), raw_output_suppressed=1),
                   dict(self.result(), model_executed=0),
                   dict(self.result(), returncode=True), [], None]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                probe.classification(json.dumps(value))

    def test_unexpected_raw_or_email_fields_rejected_without_echo(self):
        for field in ('raw', 'stdout', 'stderr', 'email', 'token'):
            value = dict(self.result(), **{field: 'secret-marker@example.invalid'})
            with self.subTest(field=field), self.assertRaises(RuntimeError) as error:
                probe.classification(json.dumps(value))
            self.assertNotIn('secret-marker', str(error.exception))

    def setup_main(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        registration = {'roles': {role: {'name': 'e-base-'+role}
                                 for role in probe.TEN_TARGETS}}
        stack.enter_context(patch.object(probe, 'require_managed_namespace'))
        stack.enter_context(patch.object(probe.signal, 'signal'))
        stack.enter_context(patch.object(Path, 'read_text', return_value=json.dumps(registration)))
        stack.enter_context(patch.object(probe, 'SandboxRuntime'))
        stack.enter_context(patch('builtins.open', mock_open()))
        stack.enter_context(patch.object(probe.fcntl, 'flock'))
        inventory = stack.enter_context(patch.object(probe, 'inventory'))
        create = stack.enter_context(patch.object(probe.tempfile, 'mkdtemp',
            return_value='/home/fleet/controller-validation/auth-inventory-mock'))
        receipts = []
        write = stack.enter_context(patch.object(probe, 'atomic_write_json',
            side_effect=lambda path, value: receipts.append(deepcopy(value))))
        output = stack.enter_context(patch('builtins.print'))
        def result(*args, **kwargs):
            if args[0] == 'policy':
                return json.dumps({'rules': [{'scope': 'sandbox:'+args[2],
                    'resource_type': 'network', 'decision': 'deny',
                    'status': 'active', 'resources': ['**']}]})
            if args[0] == 'exec':
                return json.dumps(self.result())
            return ''
        run = stack.enter_context(patch.object(probe, 'run', side_effect=result))
        return run, create, write, receipts, inventory, output

    def test_missing_last_denial_blocks_every_guest_exec(self):
        run, create, write, receipts, inventory, output = self.setup_main()
        normal = run.side_effect
        def result(*args, **kwargs):
            if args[:3] == ('policy', 'ls', 'e-base-'+probe.TEN_TARGETS[-1]):
                return json.dumps({'rules': []})
            return normal(*args, **kwargs)
        run.side_effect = result
        with self.assertRaisesRegex(RuntimeError, 'networks must remain denied'):
            probe.main()
        self.assertEqual(run.call_args_list, [
            call('policy', 'ls', 'e-base-'+role, '--json') for role in probe.TEN_TARGETS])
        create.assert_not_called()
        write.assert_not_called()

    def test_guest_failure_stops_attempted_role_and_never_advances(self):
        run, create, write, receipts, inventory, output = self.setup_main()
        normal = run.side_effect
        def result(*args, **kwargs):
            if args[0] == 'exec':
                raise RuntimeError('guest failed')
            return normal(*args, **kwargs)
        run.side_effect = result
        with self.assertRaisesRegex(RuntimeError, 'guest failed'):
            probe.main()
        first = 'e-base-'+probe.TEN_TARGETS[0]
        self.assertEqual(run.call_args_list[10:], [
            call('exec', first, '/usr/bin/python3', '-I', '-c', probe.PROBE, timeout=45),
            call('stop', first)])
        self.assertEqual(inventory.call_count, 3)
        self.assertEqual(receipts[-1]['roles'], {})
        self.assertEqual(receipts[-1]['phase'], 'checking')
        self.assertIs(receipts[-1]['all_vms_stopped'], True)

    def test_all_ten_sequential_successes_stop_before_next_role(self):
        run, create, write, receipts, inventory, output = self.setup_main()
        probe.main()
        expected = []
        for role in probe.TEN_TARGETS:
            expected.extend([
                call('exec', 'e-base-'+role, '/usr/bin/python3', '-I', '-c', probe.PROBE, timeout=45),
                call('stop', 'e-base-'+role)])
        self.assertEqual(run.call_args_list[10:], expected)
        self.assertEqual(inventory.call_count, 12)
        self.assertEqual(receipts[-1]['phase'], 'complete')
        self.assertEqual(set(receipts[-1]['roles']), set(probe.TEN_TARGETS))
        self.assertIs(receipts[-1]['all_vms_stopped'], True)
        for receipt in receipts:
            self.assertIs(receipt['model_executed'], False)
            self.assertIs(receipt['credentials_copied'], False)
            self.assertIs(receipt['raw_output_suppressed'], True)

    def test_unrecognized_guest_output_still_stops_without_recording_raw(self):
        run, create, write, receipts, inventory, output = self.setup_main()
        normal = run.side_effect
        def result(*args, **kwargs):
            if args[0] == 'exec':
                return json.dumps(dict(self.result(), email='secret-marker@example.invalid'))
            return normal(*args, **kwargs)
        run.side_effect = result
        with self.assertRaisesRegex(RuntimeError, 'refusing raw output'):
            probe.main()
        self.assertEqual(run.call_args_list[-1], call('stop', 'e-base-'+probe.TEN_TARGETS[0]))
        self.assertNotIn('secret-marker', json.dumps(receipts))
        self.assertNotIn('secret-marker', str(output.call_args_list))


if __name__ == '__main__':
    unittest.main()
