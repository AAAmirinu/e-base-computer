"""Local inventory tests with synthetic directories; no VM or Git operations."""
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import candidate_review_store as store
import sandbox_driver as driver


class CandidateInventoryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.root.chmod(0o700)
        self.queue = self.root / 'candidate-review'
        self.registration = dict(controller_root=str(self.root),
            migration_epoch='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa')
        self.good = {'evidence': {'commit': 'b' * 40, 'turn_binding': {'role': 'machine'}}}
        guard = patch.object(store, 'inspect_candidate', return_value=self.good)
        self.inspect = guard.start()
        self.addCleanup(guard.stop)

    def operation(self, number):
        self.queue.mkdir(mode=0o700, exist_ok=True)
        name = format(number, '032x')
        (self.queue / name).mkdir(mode=0o700)
        return name

    def invoke(self):
        result = store.inspect_candidates(self.root, self.registration)
        self.assertIs(result['runtime_state_observed'], False)
        self.assertIs(result['resume_available'], False)
        return result

    def test_absent_queue(self):
        result = self.invoke()
        self.assertEqual(result['status'], 'absent')
        self.assertTrue(result['inventory_complete'])
        self.inspect.assert_not_called()

    def test_unknown_registration_does_not_inspect(self):
        for registration in ({}, {'controller_root': str(self.root)},
                             dict(self.registration, controller_root=str(self.root / 'other'))):
            with self.subTest(registration=registration):
                self.registration = registration
                self.assertEqual(self.invoke()['status'], 'registration_missing_or_mismatched')
        self.inspect.assert_not_called()

    def test_verified_record_remains_pending_review(self):
        name = self.operation(1)
        result = self.invoke()
        self.assertEqual(result['records'][name], dict(state='pending_review', archive_verified=True,
                                                       commit='b' * 40, role='machine'))
        self.assertTrue(result['inventory_complete'])

    def test_partial_record_is_not_verified(self):
        name = self.operation(1)
        self.inspect.side_effect = FileNotFoundError('synthetic missing receipt')
        result = self.invoke()
        self.assertEqual(result['records'][name], dict(state='incomplete', archive_verified=False))

    def test_corrupt_record_is_inspection_required_without_exception_text(self):
        name = self.operation(1)
        for error in (ValueError('PRIVATE_DETAILS'), TypeError('PRIVATE_DETAILS'),
                      KeyError('PRIVATE_DETAILS'), OSError('PRIVATE_DETAILS'), RecursionError('PRIVATE_DETAILS')):
            with self.subTest(error=type(error).__name__):
                self.inspect.side_effect = error
                result = self.invoke()
                self.assertEqual(result['records'][name]['state'], 'inspection_required')
                self.assertFalse(result['records'][name]['archive_verified'])
                self.assertNotIn('PRIVATE_DETAILS', json.dumps(result))

    def test_invalid_name_and_regular_file_report_partial(self):
        self.queue.mkdir(mode=0o700)
        (self.queue / 'not-an-operation').mkdir()
        (self.queue / ('c' * 32)).write_bytes(b'not a directory')
        result = self.invoke()
        self.assertEqual(result['invalid_entry_count'], 2)
        self.assertEqual(result['status'], 'partial_inventory')
        self.assertFalse(result['inventory_complete'])
        self.inspect.assert_not_called()

    @unittest.skipUnless(os.name == 'posix', 'Symlink support required')
    def test_operation_symlink_not_followed(self):
        self.queue.mkdir(mode=0o700)
        (self.queue / ('d' * 32)).symlink_to(self.root, target_is_directory=True)
        result = self.invoke()
        self.assertEqual(result['invalid_entry_count'], 1)
        self.assertFalse(result['inventory_complete'])
        self.inspect.assert_not_called()

    @unittest.skipUnless(os.name == 'posix', 'Symlink support required')
    def test_queue_symlink_rejected(self):
        self.queue.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.invoke()
        self.inspect.assert_not_called()

    def test_only_first_32_sorted_operations_examined(self):
        for number in reversed(range(35)):
            self.operation(number)
        result = self.invoke()
        self.assertEqual(list(result['records']), [format(i, '032x') for i in range(32)])
        self.assertEqual(self.inspect.call_count, 32)
        self.assertEqual(result['unexamined_count'], 3)
        self.assertEqual(result['status'], 'partial_inventory')

    def test_256_entries_allow_bounded_detail_inspection(self):
        for number in range(256):
            self.operation(number)
        result = self.invoke()
        self.assertEqual(self.inspect.call_count, 32)
        self.assertEqual(result['unexamined_count'], 224)
        self.assertEqual(result['status'], 'partial_inventory')

    def test_257_entries_refuse_detail_inspection(self):
        for number in range(257):
            self.operation(number)
        result = self.invoke()
        self.assertEqual(result['status'], 'inventory_limit_exceeded')
        self.assertFalse(result['inventory_complete'])
        self.inspect.assert_not_called()

    def test_driver_inventory_and_single_inspection_never_construct_transport(self):
        registry = self.root / 'registry.json'
        registry.write_text(json.dumps(self.registration))
        for command, target in (('inspect-candidates', 'inspect_candidates'),
                                ('inspect-candidate', 'inspect_candidate')):
            with self.subTest(command=command):
                args = SimpleNamespace(root=str(self.root), registry=str(registry),
                                       command=command, operation='a' * 32)
                transport = Mock()
                with patch.object(driver, 'LinuxTransport', side_effect=AssertionError('No transport')) as factory, \
                        patch.object(driver, 'SandboxRuntime', side_effect=AssertionError('No runtime')) as runtime, \
                        patch.object(driver, target, return_value={'local': True}) as inspect:
                    self.assertEqual(driver.execute(args, transport), {'local': True})
                factory.assert_not_called()
                runtime.assert_not_called()
                self.assertEqual(transport.mock_calls, [])
                inspect.assert_called_once()


if __name__ == '__main__':
    unittest.main()
