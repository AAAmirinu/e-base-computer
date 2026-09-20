"""Private temporary-file tests; no VM, Git, model, or candidate execution."""
import hashlib
import json
import os
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import candidate_review_store as store
from test_snapshot_git_tree import snapshot
import test_candidate_evidence_binding as binding_fixtures
from sandbox_turn_fence import reserve_turn


@unittest.skipUnless(sys.platform == 'linux' and hasattr(os, 'O_NOFOLLOW'), 'Linux private-store boundary')
class CandidateReviewStoreTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.root.chmod(0o700)
        self.binding = dict(operation_id='a' * 32,
            migration_epoch='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', role='machine', sequence=3,
            sandbox_id='cccccccc-cccc-4ccc-8ccc-cccccccccccc')
        self.registration = dict(controller_root=str(self.root))
        self.bundle = b'synthetic opaque bundle'
        raw, digest, blobs = snapshot([])
        self.evidence = dict(bundle=self.bundle, manifest_raw=raw, manifest_sha256=digest, blobs=blobs,
                             dispatch_raw=b'{"synthetic":"dispatch"}', stdout_raw=b'synthetic stdout',
                             build_raw=b'{"synthetic":"build"}', import_raw=b'{"synthetic":"import"}')
        fences = self.root / 'model-turn-fences'
        fences.mkdir(mode=0o700)
        self.fence = fences / 'machine.json'
        self.reservation = dict(self.binding, schema=1, run_directory=str(self.root / 'turn'),
                                state='unresolved', automatic_resume=False)
        self.write_fence()
        self.original_fence = self.fence.read_bytes()
        self.work = self.root / 'candidate-review' / self.binding['operation_id']
        self.verified = dict(review_required=True, fence_release_authorized=False,
                             resume_available=False, production_accepted=False,
                             turn_binding=dict(self.binding), manifest_sha256=digest,
                             validator_id='dddddddd-dddd-4ddd-8ddd-dddddddddddd', image_id='sha256:' + 'e' * 64)
        guard = patch.object(store, 'bind_turn_candidate', return_value=self.verified)
        self.bind = guard.start()
        self.addCleanup(guard.stop)

    def write_fence(self):
        self.fence.write_text(json.dumps(self.reservation), encoding='utf-8')
        self.fence.chmod(0o600)

    def invoke(self):
        return store.record_candidate(self.root, self.registration, self.binding, **self.evidence)

    def assert_hold(self):
        self.assertTrue(self.work.is_dir())
        self.assertEqual(self.fence.read_bytes(), self.original_fence)
        with self.assertRaises(FileExistsError):
            self.invoke()

    def test_success_persists_bundle_without_releasing_fence(self):
        path = self.invoke()
        self.assertEqual(path, self.work / 'candidate.json')
        receipt = json.loads(path.read_bytes())
        self.assertEqual(receipt['phase'], 'pending_review')
        self.assertEqual(receipt['evidence'], self.verified)
        self.assertEqual(receipt['fence_sha256'], hashlib.sha256(self.original_fence).hexdigest())
        self.assertEqual((self.work / 'candidate.bundle').read_bytes(), self.bundle)
        self.assertEqual(self.fence.read_bytes(), self.original_fence)
        for key in ('published', 'merged', 'fence_released', 'resume_available'):
            self.assertIs(receipt[key], False)
        for key, name in (('dispatch_raw', 'dispatch.json'), ('stdout_raw', 'stdout.log'),
                          ('build_raw', 'build.json'), ('import_raw', 'import.json')):
            self.assertEqual((self.work / name).read_bytes(), self.evidence[key])
        self.assertEqual((self.work / 'source-snapshot' / 'manifest.json').read_bytes(),
                         self.evidence['manifest_raw'])
        self.bind.assert_called_once_with(self.binding, self.registration, **self.evidence)

    def test_duplicate_operation_refused_without_overwriting_receipt(self):
        path = self.invoke()
        before = path.read_bytes()
        with self.assertRaises(FileExistsError):
            self.invoke()
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.fence.read_bytes(), self.original_fence)

    def test_other_operation_epoch_vm_sequence_refused_before_queue(self):
        original = dict(self.reservation)
        for key, value in (('operation_id', 'd' * 32),
                           ('migration_epoch', 'dddddddd-dddd-4ddd-8ddd-dddddddddddd'),
                           ('sandbox_id', 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee'),
                           ('sequence', 4)):
            with self.subTest(key=key):
                self.reservation = dict(original, **{key: value})
                self.write_fence()
                with self.assertRaises(ValueError):
                    self.invoke()
                self.assertFalse((self.root / 'candidate-review').exists())

    def test_binding_rejection_leaves_no_queue(self):
        self.bind.side_effect = ValueError('invalid binding')
        with self.assertRaises(ValueError):
            self.invoke()
        self.assertFalse((self.root / 'candidate-review').exists())
        self.assertEqual(self.fence.read_bytes(), self.original_fence)

    def test_bundle_open_failure_leaves_hold_and_refuses_retry(self):
        original_open = store.os.open
        def fail_bundle(path, *args, **kwargs):
            if Path(path).name == 'candidate.bundle':
                raise OSError('synthetic bundle failure')
            return original_open(path, *args, **kwargs)
        with patch.object(store.os, 'open', side_effect=fail_bundle):
            with self.assertRaises(OSError):
                self.invoke()
        self.assertFalse((self.work / 'candidate.json').exists())
        self.assert_hold()

    def test_final_receipt_failure_leaves_bundle_and_hold(self):
        with patch.object(store, 'atomic_write_json', side_effect=OSError('receipt failure')):
            with self.assertRaises(OSError):
                self.invoke()
        self.assertEqual((self.work / 'candidate.bundle').read_bytes(), self.bundle)
        self.assertFalse((self.work / 'candidate.json').exists())
        self.assert_hold()

    def test_directory_sync_failure_after_reservation_leaves_hold(self):
        original = store._sync_directory
        def fail_work(path):
            if path == self.work:
                raise OSError('directory sync failure')
            return original(path)
        with patch.object(store, '_sync_directory', side_effect=fail_work):
            with self.assertRaises(OSError):
                self.invoke()
        self.assert_hold()

    def test_changed_fence_after_bundle_write_refuses_final_receipt(self):
        original = store._file
        reads = []
        def changed(path, limit):
            reads.append(path)
            raw = original(path, limit)
            return raw if len(reads) == 1 else raw + b' '
        with patch.object(store, '_file', side_effect=changed):
            with self.assertRaisesRegex(RuntimeError, 'Reservation changed'):
                self.invoke()
        self.assertFalse((self.work / 'candidate.json').exists())
        self.assert_hold()

    def test_symlink_root_refused_before_binding(self):
        link = self.root / 'root-link'
        link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            store.record_candidate(link, dict(controller_root=str(link)), self.binding, bundle=self.bundle)
        self.bind.assert_not_called()

    def test_symlink_queue_refused(self):
        elsewhere = self.root / 'elsewhere'
        elsewhere.mkdir(mode=0o700)
        (self.root / 'candidate-review').symlink_to(elsewhere, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.invoke()
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_inspect_revalidates_archive_without_writes_or_fence_changes(self):
        path = self.invoke()
        original = path.read_bytes()
        self.bind.reset_mock()
        with patch.object(store, 'atomic_write_json', side_effect=AssertionError('Read only')) as write:
            result = store.inspect_candidate(self.root, self.registration, self.binding['operation_id'])
        self.assertTrue(result['archive_verified'])
        self.assertFalse(result['runtime_state_observed'])
        self.bind.assert_called_once()
        self.assertEqual(self.bind.call_args.kwargs['bundle'], self.bundle)
        write.assert_not_called()
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(self.fence.read_bytes(), self.original_fence)

    def test_inspect_changed_fence_rejected(self):
        self.invoke()
        self.reservation['sequence'] += 1
        self.write_fence()
        with self.assertRaisesRegex(ValueError, 'Reservation changed'):
            store.inspect_candidate(self.root, self.registration, self.binding['operation_id'])

    def test_inspect_corrupt_bundle_reaches_revalidation_and_is_rejected(self):
        self.invoke()
        (self.work / 'candidate.bundle').write_bytes(b'corrupt')
        def revalidate(binding, registration, **evidence):
            self.assertEqual(evidence['bundle'], b'corrupt')
            raise ValueError('Bundle digest mismatch')
        self.bind.side_effect = revalidate
        with self.assertRaisesRegex(ValueError, 'Bundle digest mismatch'):
            store.inspect_candidate(self.root, self.registration, self.binding['operation_id'])
        self.assertEqual(self.fence.read_bytes(), self.original_fence)


@unittest.skipUnless(sys.platform == 'linux' and hasattr(os, 'O_NOFOLLOW'), 'Linux private-store boundary')
class CandidateReviewIntegrationTests(unittest.TestCase):
    def test_actual_binder_reservation_archive_and_reinspection(self):
        fixture = binding_fixtures.TurnCandidateBindingTests()
        fixture.setUp()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            root.chmod(0o700)
            registration = dict(fixture.registration, controller_root=str(root))
            receipt = dict(fixture.turn_binding, schema=1)
            fence = reserve_turn(root, receipt, root / 'synthetic-turn')
            fence_before = fence.read_bytes()
            path = store.record_candidate(root, registration, fixture.turn_binding, **fixture.packet())
            saved_before = path.read_bytes()
            inspected = store.inspect_candidate(root, registration, fixture.turn_binding['operation_id'])
            self.assertTrue(inspected['archive_verified'])
            self.assertTrue(inspected['evidence']['turn_bound'])
            self.assertTrue(inspected['evidence']['candidate_import_verified'])
            self.assertFalse(inspected['evidence']['fence_release_authorized'])
            self.assertFalse(inspected['resume_available'])
            self.assertEqual(path.read_bytes(), saved_before)
            self.assertEqual(fence.read_bytes(), fence_before)
            with self.assertRaises(FileExistsError):
                store.record_candidate(root, registration, fixture.turn_binding, **fixture.packet())


if __name__ == '__main__':
    unittest.main()
