"""Read-only crash-fence classification; never launch a VM or trust run paths."""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import sandbox_turn_fence as fence


class TurnInspectionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.root.chmod(0o700)
        self.directory = self.root / 'model-turn-fences'
        self.path = self.directory / 'machine.json'
        self.receipt = {
            'schema': 1, 'operation_id': 'a' * 32,
            'migration_epoch': 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
            'role': 'machine', 'sequence': 0,
            'sandbox_id': 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
        }
        self.registration = {
            'migration_epoch': self.receipt['migration_epoch'],
            'controller_root': str(self.root),
            'roles': {role: {'id': self.receipt['sandbox_id'],
                             'name': 'e-base-' + role} for role in fence.ROLES},
        }

    def inspect(self):
        return fence.inspect_turn_fences(self.root, self.registration)

    def reserve(self):
        fence.reserve_turn(self.root, self.receipt, self.root / 'nonexistent-run')
        return json.loads(self.path.read_bytes())

    def write(self, value):
        self.path.write_text(json.dumps(value), encoding='utf-8')

    def state(self):
        result = self.inspect()
        self.assertIs(result['resume_available'], False)
        self.assertIs(result['runtime_state_observed'], False)
        self.assertEqual(set(result['roles']), fence.ROLES)
        return result['roles']['machine']['state']

    def symlink(self, link, target, directory=False):
        try:
            link.symlink_to(target, target_is_directory=directory)
        except (OSError, NotImplementedError) as error:
            self.skipTest('Symlinks unavailable: ' + str(error))

    def test_missing_fences_is_absent_without_creating_anything(self):
        (self.root / 'STOP').write_bytes(b'keep stopped\n')
        before = sorted(self.root.iterdir())
        result = self.inspect()
        self.assertEqual(sorted(self.root.iterdir()), before)
        self.assertTrue(all(item['state'] == 'absent' for item in result['roles'].values()))
        self.assertFalse(result['resume_available'])
        self.assertFalse(result['runtime_state_observed'])

    def test_valid_reservation_is_immutable_and_never_runs_commands(self):
        self.reserve()
        (self.root / 'STOP').write_bytes(b'preserve STOP')
        before = self.path.read_bytes()
        metadata = self.path.stat()
        registration = copy.deepcopy(self.registration)
        with patch('subprocess.Popen', side_effect=AssertionError('No process allowed')):
            result = self.inspect()
        self.assertEqual(result['roles']['machine'], {
            'state': 'unresolved', 'sha256': hashlib.sha256(before).hexdigest()})
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.path.stat().st_mtime_ns, metadata.st_mtime_ns)
        self.assertEqual((self.root / 'STOP').read_bytes(), b'preserve STOP')
        self.assertEqual(self.registration, registration)
        self.assertFalse((self.root / 'nonexistent-run').exists())

    def test_record_run_path_is_not_followed(self):
        value = self.reserve()
        target = self.root / 'do-not-read'
        target.write_bytes(b'not JSON and not a directory')
        value['run_directory'] = str(target)
        self.write(value)
        self.assertEqual(self.state(), 'unresolved')
        self.assertEqual(target.read_bytes(), b'not JSON and not a directory')

    def test_partial_oversized_or_duplicate_json_is_invalid_and_preserved(self):
        self.reserve()
        for raw in (b'', b'{', b'null', b'[]', b'x' * (1024 * 1024),
                    b'{"schema":1,"schema":1}', b'\xff'):
            with self.subTest(raw=raw[:30]):
                self.path.write_bytes(raw)
                self.assertEqual(self.state(), 'invalid')
                self.assertEqual(self.path.read_bytes(), raw)

    def test_invalid_fields_are_not_accepted_as_reservations(self):
        original = self.reserve()
        for key, value in (
                ('schema', True), ('schema', 2), ('sequence', True),
                ('sequence', -1), ('sequence', 0.0),
                ('operation_id', 'A' * 32), ('operation_id', 'g' * 32),
                ('migration_epoch', original['migration_epoch'].upper()),
                ('sandbox_id', original['sandbox_id'].upper()),
                ('role', 'stdlib'), ('role', '../machine'),
                ('state', 'complete'), ('automatic_resume', 0),
                ('automatic_resume', True), ('run_directory', 'relative'),
                ('extra', 'unexpected')):
            with self.subTest(key=key, value=value):
                self.write(dict(original, **{key: value}))
                self.assertEqual(self.state(), 'invalid')
        for key in original:
            with self.subTest(missing=key):
                value = dict(original)
                del value[key]
                self.write(value)
                self.assertEqual(self.state(), 'invalid')

    def test_identity_mismatch_never_clears_fence(self):
        original = self.reserve()
        for key, value in (
                ('migration_epoch', 'cccccccc-cccc-4ccc-8ccc-cccccccccccc'),
                ('sandbox_id', 'dddddddd-dddd-4ddd-8ddd-dddddddddddd')):
            with self.subTest(key=key):
                self.write(dict(original, **{key: value}))
                before = self.path.read_bytes()
                self.assertEqual(self.state(), 'identity_mismatch')
                self.assertEqual(self.path.read_bytes(), before)

    def test_registration_root_mismatch_preserves_unresolved_fence(self):
        self.reserve()
        original = self.path.read_bytes()
        self.registration['controller_root'] = str(self.root / 'another-root')
        self.assertEqual(self.state(), 'identity_mismatch')
        self.assertEqual(self.path.read_bytes(), original)

    def test_directory_in_place_of_entry_is_invalid(self):
        self.directory.mkdir(mode=0o700)
        self.path.mkdir(mode=0o700)
        self.assertEqual(self.state(), 'invalid')

    def test_oversize_entry_does_not_publish_partial_digest(self):
        self.reserve()
        self.path.write_bytes(b'x' * 65537)
        self.assertEqual(self.inspect()['roles']['machine'], {'state': 'invalid'})

    def test_report_never_includes_recorded_path_or_untrusted_text(self):
        value = self.reserve()
        value['run_directory'] = str(self.root / 'secret-path-do-not-disclose')
        self.write(value)
        encoded = json.dumps(self.inspect())
        self.assertNotIn('secret-path-do-not-disclose', encoded)
        self.assertNotIn('run_directory', encoded)

    @unittest.skipIf(os.name == 'nt', 'POSIX hard links')
    def test_hardlinked_entry_is_invalid(self):
        self.reserve()
        target = self.root / 'second-link'
        os.link(self.path, target)
        original = target.read_bytes()
        self.assertEqual(self.state(), 'invalid')
        self.assertEqual(target.read_bytes(), original)

    def test_symlink_entry_is_invalid_and_target_untouched(self):
        self.directory.mkdir(mode=0o700)
        target = self.root / 'outside-record'
        target.write_bytes(b'preserve')
        self.symlink(self.path, target)
        self.assertEqual(self.state(), 'invalid')
        self.assertEqual(target.read_bytes(), b'preserve')
        self.assertTrue(self.path.is_symlink())

    def test_symlink_directory_is_refused(self):
        target = self.root / 'elsewhere'
        target.mkdir(mode=0o700)
        self.symlink(self.directory, target, directory=True)
        with self.assertRaises(ValueError):
            self.inspect()
        self.assertEqual(list(target.iterdir()), [])

    @unittest.skipIf(os.name == 'nt', 'POSIX FIFO and permission checks')
    def test_fifo_is_invalid_without_opening_or_blocking(self):
        self.directory.mkdir(mode=0o700)
        os.mkfifo(self.path, mode=0o600)
        self.assertEqual(self.state(), 'invalid')

    @unittest.skipIf(os.name == 'nt', 'POSIX permissions')
    def test_public_fence_directory_is_refused(self):
        self.directory.mkdir(mode=0o755)
        with self.assertRaises(ValueError):
            self.inspect()


if __name__ == '__main__':
    unittest.main()
