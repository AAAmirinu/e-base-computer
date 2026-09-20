"""Durable role reservations only; no VM or model execution."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import sandbox_turn_fence as fence


class TurnFenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.root.chmod(0o700)
        self.run = self.root / 'first-run'
        self.receipt = {
            'schema': 1, 'operation_id': 'a' * 32,
            'migration_epoch': 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
            'role': 'machine', 'sequence': 0,
            'sandbox_id': 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
        }
        self.directory = self.root / 'model-turn-fences'
        self.path = self.directory / 'machine.json'

    def reserve(self, receipt=None, run=None):
        return fence.reserve_turn(self.root, receipt or self.receipt, run or self.run)

    def symlink(self, link, target, directory=False):
        try:
            link.symlink_to(target, target_is_directory=directory)
        except (OSError, NotImplementedError) as error:
            self.skipTest('Symlinks unavailable: ' + str(error))

    def test_reservation_binds_identity_and_remains_unresolved(self):
        self.assertEqual(self.reserve(), self.path)
        value = json.loads(self.path.read_bytes())
        self.assertEqual(value, dict(self.receipt, run_directory=str(self.run),
                                    state='unresolved', automatic_resume=False))
        self.assertFalse(self.run.exists())
        if os.name != 'nt':
            self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(self.directory.stat().st_mode & 0o777, 0o700)

    def test_existing_empty_or_malformed_reservation_is_unchanged(self):
        self.directory.mkdir(mode=0o700)
        for raw in (b'', b'{broken', b'null\n'):
            with self.subTest(raw=raw):
                self.path.write_bytes(raw)
                with self.assertRaisesRegex(RuntimeError, 'Unresolved prior'):
                    self.reserve()
                self.assertEqual(self.path.read_bytes(), raw)

    def test_changed_identity_or_output_does_not_bypass_role_fence(self):
        self.reserve()
        original = self.path.read_bytes()
        changes = ({'operation_id': 'c' * 32}, {'sequence': 99},
                   {'migration_epoch': 'cccccccc-cccc-4ccc-8ccc-cccccccccccc'},
                   {'sandbox_id': 'dddddddd-dddd-4ddd-8ddd-dddddddddddd'}, {})
        for change in changes:
            with self.subTest(change=change):
                with self.assertRaisesRegex(RuntimeError, 'Unresolved prior'):
                    self.reserve(dict(self.receipt, **change), self.root / 'different-run')
                self.assertEqual(self.path.read_bytes(), original)

    def test_independent_roles_can_reserve(self):
        self.reserve()
        other = dict(self.receipt, role='coordinator', operation_id='c' * 32,
                     sandbox_id='cccccccc-cccc-4ccc-8ccc-cccccccccccc')
        path = self.reserve(other, self.root / 'coordinator-run')
        self.assertEqual(path, self.directory / 'coordinator.json')
        self.assertTrue(self.path.exists())

    def test_symlink_fences_directory_is_refused(self):
        target = self.root / 'elsewhere'
        target.mkdir(mode=0o700)
        self.symlink(self.directory, target, directory=True)
        with self.assertRaises(ValueError):
            self.reserve()
        self.assertEqual(list(target.iterdir()), [])

    def test_symlink_fence_is_refused_without_touching_target(self):
        self.directory.mkdir(mode=0o700)
        target = self.root / 'target'
        target.write_bytes(b'preserve')
        self.symlink(self.path, target)
        with self.assertRaisesRegex(RuntimeError, 'Unresolved prior'):
            self.reserve()
        self.assertEqual(target.read_bytes(), b'preserve')
        self.assertTrue(self.path.is_symlink())

    def test_file_fsync_failure_leaves_blocking_reservation(self):
        with patch.object(fence, '_sync_directory'), \
                patch.object(fence.os, 'fsync', side_effect=OSError('sync failed')):
            with self.assertRaisesRegex(OSError, 'sync failed'):
                self.reserve()
        self.assertTrue(self.path.exists())
        original = self.path.read_bytes()
        with self.assertRaisesRegex(RuntimeError, 'Unresolved prior'):
            self.reserve()
        self.assertEqual(self.path.read_bytes(), original)

    def test_final_directory_sync_failure_leaves_blocking_reservation(self):
        with patch.object(fence, '_sync_directory', side_effect=[None, OSError('directory sync')]):
            with self.assertRaisesRegex(OSError, 'directory sync'):
                self.reserve()
        self.assertTrue(self.path.exists())
        with self.assertRaisesRegex(RuntimeError, 'Unresolved prior'):
            self.reserve()

    def test_parallel_reservations_have_exactly_one_winner(self):
        barrier = threading.Barrier(4)

        def attempt(number):
            receipt = dict(self.receipt, operation_id=str(number) * 32)
            barrier.wait(timeout=10)
            try:
                self.reserve(receipt, self.root / ('run-' + str(number)))
            except RuntimeError as error:
                self.assertIn('Unresolved prior', str(error))
                return None
            return receipt['operation_id']

        with ThreadPoolExecutor(max_workers=4) as pool:
            winners = [result for result in pool.map(attempt, range(1, 5)) if result]
        self.assertEqual(len(winners), 1)
        self.assertEqual(json.loads(self.path.read_bytes())['operation_id'], winners[0])


if __name__ == '__main__':
    unittest.main()
