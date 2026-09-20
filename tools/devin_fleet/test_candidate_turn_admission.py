"""Private-file admission tests without VM, Git, or source execution."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import candidate_turn_admission as admission


@unittest.skipUnless(os.name == 'posix', 'Linux controller boundary')
class CandidateTurnAdmissionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.base.chmod(0o700)
        self.root = self.base / 'controller'
        self.root.mkdir(mode=0o700)
        self.run = self.root / 'model-turn'
        self.run.mkdir(mode=0o700)
        self.fences = self.root / 'model-turn-fences'
        self.fences.mkdir(mode=0o700)
        self.fence = self.fences / 'machine.json'
        self.registry_path = self.base / 'sandbox-registry.json'
        self.binding = dict(operation_id='a' * 32, sequence=2, role='machine',
            migration_epoch='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
            sandbox_id='cccccccc-cccc-4ccc-8ccc-cccccccccccc',
            manifest_sha256='d' * 64, base='e' * 40, turn_sha256='f' * 64, capture_sha256='1' * 64)
        self.registration = dict(controller_root=str(self.root), production_enabled=True,
            validation_image_id='sha256:cee9fe9272c17a34c0b1620485843ff67431dcc18d2e0f7380581fe28f5aeaf4',
            migration_epoch=self.binding['migration_epoch'],
            roles={'machine': {'id': self.binding['sandbox_id']}})
        self.reservation = {key: self.binding[key] for key in (
            'operation_id', 'sequence', 'role', 'migration_epoch', 'sandbox_id')}
        self.reservation.update(schema=1, run_directory=str(self.run), state='unresolved', automatic_resume=False)
        self.write(self.registry_path, self.registration)
        self.write(self.fence, self.reservation)
        self.patch('ROOT', self.base)
        self.snapshot = self.patch('load_snapshot', return_value=(b'manifest', {}, {'files': []}))
        self.capture = self.patch('load_capture', return_value={'capture': {}})
        self.turn = self.patch('load_turn_binding', return_value=copy.deepcopy(self.binding))

    def patch(self, name, *args, **kwargs):
        context = patch.object(admission, name, *args, **kwargs)
        value = context.start()
        self.addCleanup(context.stop)
        return value

    def write(self, path, value):
        path.write_text(json.dumps(value), encoding='utf-8')
        path.chmod(0o600)

    def make(self):
        return admission.make_admission(self.registration, self.binding)

    def test_success_can_recheck_without_modifying_fence_or_registry(self):
        fence, registry = self.fence.read_bytes(), self.registry_path.read_bytes()
        check = self.make()
        check()
        check()
        self.assertEqual(self.fence.read_bytes(), fence)
        self.assertEqual(self.registry_path.read_bytes(), registry)
        self.assertGreaterEqual(self.turn.call_count, 2)
        self.assertEqual(self.snapshot.call_args.args[:2],
                         (self.run / 'source-snapshot', self.binding['manifest_sha256']))

    def test_dangling_stop_symlink_blocks_recheck(self):
        check = self.make()
        check()
        (self.root / 'STOP').symlink_to(self.root / 'missing-target')
        with self.assertRaises((RuntimeError, ValueError)):
            check()

    def test_registry_change_after_initial_check_rejected(self):
        check = self.make()
        check()
        self.write(self.registry_path, dict(self.registration, production_enabled=False))
        with self.assertRaises(ValueError):
            check()

    def test_explicit_registration_checker_is_rechecked(self):
        calls=[]
        checker=lambda value:calls.append(copy.deepcopy(value))
        with patch('prepared_candidate_trial_state.check_runtime_registration', checker):
            check=admission.make_admission(self.registration,self.binding,
                registration_check=checker)
            check();check()
        self.assertEqual(calls,[self.registration,self.registration,self.registration])
        with self.assertRaisesRegex(ValueError, 'fixed prepared-candidate'):
            admission.make_admission(self.registration,self.binding,
                                     registration_check=lambda value: None)

    def test_same_identity_fence_reformat_is_rejected(self):
        check = self.make()
        check()
        self.fence.write_text(json.dumps(self.reservation, indent=2), encoding='utf-8')
        with self.assertRaises(ValueError):
            check()

    def test_epoch_role_and_vm_mismatch_rejected(self):
        for key, value in (('migration_epoch', 'dddddddd-dddd-4ddd-8ddd-dddddddddddd'),
                           ('role', 'stdlib'), ('sandbox_id', 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee'),
                           ('sequence', True), ('operation_id', '2' * 32)):
            with self.subTest(key=key):
                original = self.binding
                self.binding = dict(original, **{key: value})
                try:
                    with self.assertRaises(ValueError):
                        self.make()()
                finally:
                    self.binding = original

    def test_outside_run_directory_rejected_before_snapshot_read(self):
        self.write(self.fence, dict(self.reservation, run_directory=str(self.root.parent / 'outside-turn')))
        with self.assertRaises(ValueError):
            self.make()()
        self.snapshot.assert_not_called()

    def test_replaced_turn_binding_rejected(self):
        check = self.make()
        check()
        self.turn.return_value = dict(self.binding, turn_sha256='2' * 64)
        with self.assertRaises(ValueError):
            check()

    def test_caller_mutation_does_not_change_frozen_authority(self):
        check = self.make()
        self.registration['production_enabled'] = False
        self.registration['roles']['machine']['id'] = 'changed'
        self.binding['sequence'] = 999
        self.binding['manifest_sha256'] = '0' * 64
        check()

    def test_registry_symlink_rejected(self):
        target = self.root / 'registry-copy.json'
        self.registry_path.rename(target)
        self.registry_path.symlink_to(target)
        with self.assertRaises((ValueError, OSError)):
            self.make()()

    def test_fence_symlink_rejected(self):
        target = self.root / 'fence-copy.json'
        self.fence.rename(target)
        self.fence.symlink_to(target)
        with self.assertRaises((ValueError, OSError)):
            self.make()()

    def test_run_directory_symlink_rejected(self):
        linked = self.root / 'linked-turn'
        linked.symlink_to(self.run, target_is_directory=True)
        self.write(self.fence, dict(self.reservation, run_directory=str(linked)))
        with self.assertRaises(ValueError):
            self.make()()

    def test_unregistered_image_or_disabled_production_rejected(self):
        for changes in ({'production_enabled': False}, {'validation_image_id': 'sha256:' + '0' * 64}):
            with self.subTest(changes=changes):
                original = self.registration
                self.registration = dict(original, **changes)
                try:
                    self.write(self.registry_path, self.registration)
                    with self.assertRaises(ValueError):
                        self.make()()
                finally:
                    self.registration = original
                    self.write(self.registry_path, original)


if __name__ == '__main__':
    unittest.main()
