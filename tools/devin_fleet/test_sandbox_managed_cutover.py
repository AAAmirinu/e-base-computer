"""Pure maintenance cutover tests; never launch a daemon or VM."""
import copy
import hashlib
import stat
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call, patch

import managed_cutover as cut


def registry():
    return {'production_enabled': False, 'distro': 'EBase-Sandboxes',
            'user': 'fleet', 'roles': {
                role: {'name': 'e-base-' + role, 'id': 'id-' + role}
                for role in cut.ROLES}}


def inventory(expected):
    return {'sandboxes': [{'name': name, 'id': ident, 'status': 'stopped'}
                          for name, ident in expected.items()]}


class IdentityTests(unittest.TestCase):
    def test_unmigrated_or_writable_callers_rejected(self):
        path = cut.Path('/trusted/client')
        content = b'guarded client'
        digest = hashlib.sha256(content).hexdigest()
        with patch.object(cut, 'CALLER_HASHES', {path: digest}), \
                patch.object(cut.Path, 'read_bytes', return_value=content) as read, \
                patch.object(cut.Path, 'lstat') as metadata:
            metadata.return_value = SimpleNamespace(st_uid=1000, st_mode=stat.S_IFREG | 0o644)
            cut.verify_callers()
            read.return_value = b'old unguarded client'
            with self.assertRaises(RuntimeError):
                cut.verify_callers()
            read.return_value = content
            for mode, uid in ((stat.S_IFREG | 0o666, 1000), (stat.S_IFLNK | 0o644, 1000),
                              (stat.S_IFREG | 0o644, 1234)):
                metadata.return_value = SimpleNamespace(st_uid=uid, st_mode=mode)
                with self.subTest(mode=mode, uid=uid), self.assertRaises(RuntimeError):
                    cut.verify_callers()

    def test_distinct_stopped_inventory(self):
        expected = cut.expected_identities(registry())
        self.assertEqual(cut.identities(inventory(expected)), expected)

    def test_duplicate_names_ids_and_running_inventory_rejected(self):
        original = inventory(cut.expected_identities(registry()))
        for field, value in [('name', original['sandboxes'][0]['name']),
                             ('id', original['sandboxes'][0]['id']),
                             ('status', 'running')]:
            changed = copy.deepcopy(original)
            changed['sandboxes'][1][field] = value
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                cut.identities(changed)
        with self.assertRaises(RuntimeError):
            cut.identities({'sandboxes': original['sandboxes'][:-1]})

    def test_registry_requires_literal_false_production(self):
        for value in (True, 0, None, 'false', ''):
            changed = registry()
            changed['production_enabled'] = value
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                cut.expected_identities(changed)
        changed = registry()
        del changed['production_enabled']
        with self.assertRaises(RuntimeError):
            cut.expected_identities(changed)

    def test_registry_duplicate_identities_rejected(self):
        for field in ('name', 'id'):
            changed = registry()
            changed['roles']['stdlib'][field] = changed['roles']['machine'][field]
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                cut.expected_identities(changed)

    def test_loaded_definition_requires_unmodified_inactive_static_unit(self):
        valid = {'ActiveState': 'inactive', 'MainPID': '0',
                 'FragmentPath': str(cut.UNIT_PATH), 'DropInPaths': '',
                 'NeedDaemonReload': 'no', 'UnitFileState': 'static'}
        cut.validate_loaded_service(valid)
        for field, value in [('ActiveState', 'active'), ('MainPID', '12'),
                             ('FragmentPath', '/untrusted/service'),
                             ('DropInPaths', '/etc/systemd/system/override.conf'),
                             ('NeedDaemonReload', 'yes'), ('UnitFileState', 'enabled')]:
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                cut.validate_loaded_service(dict(valid, **{field: value}))
            missing = dict(valid)
            del missing[field]
            with self.subTest(missing=field), self.assertRaises(RuntimeError):
                cut.validate_loaded_service(missing)


class CutoverTests(unittest.TestCase):
    def setUp(self):
        self.expected = cut.expected_identities(registry())
        self.status = {'roles': {role: 'stopped' for role in cut.ROLES},
                       'stop_requested': False, 'mode': 'maintenance_only',
                       'resume_available': False}
        self.managed = Mock()
        self.enterContext(patch.object(cut, 'wait_pidfile'))
        self.managed.run_status.side_effect = [inventory(self.expected), self.status]
        self.saved = []
        self.stop_old = cut.CLI + ['daemon', 'stop']
        self.start = ['/usr/bin/systemctl', 'start', cut.UNIT]
        self.stop = ['/usr/bin/systemctl', 'stop', cut.UNIT]
        self.check = ['/usr/bin/systemctl', 'show', cut.UNIT, '-p', 'MainPID', '--value']
        self.command = self.enterContext(patch.object(cut, 'command', return_value='0\n'))
        self.generation = self.enterContext(patch.object(cut, 'process_start', return_value='100'))
        self.original = self.enterContext(patch.object(cut, 'validate_original'))
        self.loaded = self.enterContext(patch.object(cut, 'loaded_service'))
        self.loaded_validation = self.enterContext(patch.object(cut, 'validate_loaded_service'))
        self.exists = self.enterContext(patch.object(cut.Path, 'exists', return_value=False))

    def execute(self):
        return cut.cutover(self.expected, 321, '100', self.managed,
                           lambda record: self.saved.append(copy.deepcopy(record)))

    def assert_no_restore(self):
        self.assertTrue(all(not item['ordinary_restore_attempted'] for item in self.saved))
        self.assertNotIn(call(cut.CLI + ['daemon', 'start', '--detach']), self.command.call_args_list)

    def test_old_process_still_alive_never_starts_managed(self):
        self.exists.return_value = True
        with self.assertRaises(RuntimeError):
            self.execute()
        self.command.assert_called_once_with(self.stop_old)
        self.managed.run_status.assert_not_called()
        self.assertEqual(self.saved[-1]['phase'], 'inspection_required')
        self.assert_no_restore()

    def test_old_stop_error_never_starts_managed(self):
        self.command.side_effect = RuntimeError('stop failed')
        with self.assertRaisesRegex(RuntimeError, 'stop failed'):
            self.execute()
        self.command.assert_called_once_with(self.stop_old)
        self.exists.assert_not_called()
        self.assert_no_restore()

    def test_generation_change_has_no_command_side_effect(self):
        self.original.side_effect = RuntimeError('Original daemon generation changed')
        with self.assertRaises(RuntimeError):
            self.execute()
        self.command.assert_not_called()
        self.assert_no_restore()

    def test_changed_loaded_definition_never_stops_original(self):
        self.loaded_validation.side_effect = RuntimeError('loaded definition changed')
        with self.assertRaisesRegex(RuntimeError, 'loaded definition changed'):
            self.execute()
        self.command.assert_not_called()
        self.assert_no_restore()

    def test_start_error_stops_only_attempted_managed_service(self):
        self.command.side_effect = ['', RuntimeError('start uncertain'), '', '0\n']
        with self.assertRaisesRegex(RuntimeError, 'start uncertain'):
            self.execute()
        self.assertEqual(self.command.call_args_list,
                         [call(self.stop_old), call(self.start), call(self.stop), call(self.check)])
        self.assertTrue(self.saved[-1]['managed_stop_verified'])
        self.managed.run_status.assert_not_called()
        self.assert_no_restore()

    def test_inventory_mismatch_cleans_up_before_controller_query(self):
        changed = dict(self.expected)
        changed['e-base-machine'] = 'unexpected-id'
        self.managed.run_status.side_effect = [inventory(changed)]
        with self.assertRaisesRegex(RuntimeError, 'inventory identity mismatch'):
            self.execute()
        self.managed.run_status.assert_called_once_with()
        self.assertEqual(self.command.call_args_list,
                         [call(self.stop_old), call(self.start), call(self.stop), call(self.check)])
        self.assertTrue(self.saved[-1]['managed_stop_verified'])
        self.assert_no_restore()

    def test_cleanup_failure_remains_inspection_required(self):
        self.command.side_effect = ['', RuntimeError('start uncertain'), RuntimeError('stop uncertain')]
        with self.assertRaisesRegex(RuntimeError, 'start uncertain'):
            self.execute()
        self.assertFalse(self.saved[-1]['managed_stop_verified'])
        self.assertEqual(self.saved[-1]['phase'], 'inspection_required')
        self.assert_no_restore()

    def test_failure_journal_error_does_not_hide_original_error(self):
        self.command.side_effect = ['', RuntimeError('start uncertain'), '', '0\n']

        def save(record):
            if record['phase'] == 'inspection_required':
                raise OSError('journal unavailable')
            self.saved.append(copy.deepcopy(record))

        with self.assertRaisesRegex(RuntimeError, 'start uncertain') as raised:
            cut.cutover(self.expected, 321, '100', self.managed, save)
        self.assertTrue(getattr(raised.exception, '__notes__', []))
        self.assertEqual(self.command.call_args_list,
                         [call(self.stop_old), call(self.start), call(self.stop), call(self.check)])
        self.assert_no_restore()

    def test_success_records_maintenance_not_production(self):
        result = self.execute()
        self.assertEqual(self.command.call_args_list, [call(self.stop_old), call(self.start)])
        self.assertEqual(self.managed.run_status.call_args_list, [call(), call(controller=True)])
        self.managed.validate_service.assert_called_once_with(self.managed.service_info.return_value)
        self.assertEqual([item['phase'] for item in self.saved],
                         ['prepared', 'stopping_original', 'starting_managed', 'maintenance_managed'])
        self.assertTrue(result['all_vms_stopped'])
        self.assertFalse(result['models_executed'])
        self.assertEqual(result['controller_status'], self.status)
        self.assert_no_restore()


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.generation = self.enterContext(patch.object(cut, 'process_start', return_value='100'))
        self.text = self.enterContext(patch.object(cut.Path, 'read_text'))
        self.bytes = self.enterContext(patch.object(cut.Path, 'read_bytes',
            return_value=b'/usr/bin/sbx\0daemon\0start\0'))
        self.executable = self.enterContext(patch.object(cut.os, 'readlink', return_value='/usr/bin/sbx'))
        self.clock = self.enterContext(patch.object(cut.time, 'monotonic', return_value=0))
        self.sleep = self.enterContext(patch.object(cut.time, 'sleep'))
        self.command = self.enterContext(patch.object(cut, 'command'))
        self.status = 'Uid:\t1000\t1000\t1000\t1000\nNSpid:\t321\t2\n'

    def test_stale_pidfile_then_ready_uses_only_metadata(self):
        self.text.side_effect = [self.status, '999', self.status, '2\n']
        cut.wait_pidfile(321)
        self.sleep.assert_called_once_with(0.1)
        self.bytes.assert_called_once_with()
        self.command.assert_not_called()

    def test_never_ready_times_out_without_client_probe(self):
        self.text.side_effect = [self.status, '999', self.status, FileNotFoundError()]
        self.clock.side_effect = [0, 0.1, 10]
        with self.assertRaisesRegex(RuntimeError, 'readiness timed out'):
            cut.wait_pidfile(321)
        self.sleep.assert_called_once_with(0.1)
        self.bytes.assert_not_called()
        self.command.assert_not_called()

    def test_generation_change_rejected_before_pidfile_read(self):
        self.generation.side_effect = ['100', '101']
        with self.assertRaisesRegex(RuntimeError, 'generation changed'):
            cut.wait_pidfile(321)
        self.text.assert_not_called()
        self.sleep.assert_not_called()
        self.command.assert_not_called()


if __name__ == '__main__':
    unittest.main()
