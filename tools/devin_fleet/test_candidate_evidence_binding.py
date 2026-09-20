"""Synthetic evidence linkage only; does not parse Git bundles or execute code."""
import copy
import hashlib
import json
import unittest

from candidate_evidence_binding import bind_candidate, bind_turn_candidate
from snapshot_git_tree import expected_tree


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class CandidateEvidenceBindingTests(unittest.TestCase):
    def setUp(self):
        content = b'synthetic source data\n'
        self.blobs = {sha(content): content}
        self.manifest = encode(dict(schema=1, base='a' * 40, files=[
            dict(path='src/a.py', mode='100644', sha256=sha(content), size=len(content))]))
        self.digest = sha(self.manifest)
        self.expected = expected_tree(self.manifest, self.digest, self.blobs)
        self.validator = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
        self.image = 'sha256:' + 'b' * 64
        self.bundle = b'synthetic opaque bundle data'
        operation = '1' * 32
        self.summary = dict(receipt_path='/tmp/validation-source-' + operation + '.json', receipt={
            'schema': 1, 'operation': operation, 'container_id': '2' * 64,
            'container_name': 'e-base-check-' + operation, 'manifest_sha256': self.digest,
            'image_id': self.image, 'base': 'a' * 40, 'phase': 'complete', 'container_stopped': True,
            'validation_passed': False, 'materialization': {'manifest_sha256': self.digest, 'base': 'a' * 40},
            'boundary': {'observations_verified': True, 'full_isolation_accepted': False},
            'test_command_succeeded': True,
            'test': {'reason': 'exited', 'returncode': 0, 'reported_test_count': 7, 'output_sha256': '3' * 64}})
        self.dispatch = dict(schema=1, phase='complete', returncode=0, sandbox_id=self.validator,
            image_id=self.image, manifest_sha256=self.digest, base='a' * 40,
            validation_passed=False, validation_vm_stopped=True)
        candidate = dict(commit='c' * 40, parent='a' * 40, tree=self.expected['tree'],
            manifest_sha256=self.digest, bundle_sha256=sha(self.bundle), bundle_bytes=len(self.bundle),
            production_accepted=False, published=False)
        self.build = dict(schema=1, phase='candidate_recovered', image_id=self.image,
            all_vms_stopped=True, production_accepted=False, published=False, expected=self.expected,
            candidate=candidate, container_evidence=self.container('4', '5'))
        self.imported = dict(schema=1, phase='import_verified', mode='import_check', image_id=self.image,
            all_vms_stopped=True, production_accepted=False, published=False,
            expected=copy.deepcopy(self.expected), container_evidence=self.container('6', '7'),
            candidate=dict(candidate, import_verified=True, verified_file_count=1,
                           checked_out=False, source_executed=False))

    def container(self, identity, operation):
        return dict(image_id=self.image, passed=True, container_stopped=True,
                    container_id=identity * 64, operation=operation * 32,
                    boundary=dict(observations_verified=True, full_isolation_accepted=False))

    def packet(self):
        stdout = encode(self.summary) + b'\n'
        dispatch = dict(self.dispatch, stdout_sha256=sha(stdout), runner_summary=copy.deepcopy(self.summary))
        dispatch_raw = encode(dispatch)
        build = dict(self.build, validation_dispatch_sha256=sha(dispatch_raw))
        build_raw = encode(build)
        imported = dict(self.imported, validation_dispatch_sha256=sha(dispatch_raw),
                        origin_receipt_sha256=sha(build_raw))
        return dict(manifest_raw=self.manifest, manifest_sha256=self.digest, blobs=self.blobs,
                    dispatch_raw=dispatch_raw, stdout_raw=stdout, build_raw=build_raw,
                    import_raw=encode(imported), bundle=self.bundle,
                    validator_id=self.validator, image_id=self.image)

    def invoke(self):
        return bind_candidate(**self.packet())

    def test_malformed_nested_objects_raise_value_error(self):
        for target, key in (('validator', 'test'), ('validator', 'boundary'),
                            ('build', 'candidate'), ('build', 'container_evidence'),
                            ('imported', 'candidate'), ('imported', 'container_evidence')):
            for value in (None, [], 'invalid'):
                with self.subTest(target=target, key=key, value=value):
                    self.setUp()
                    record = self.summary['receipt'] if target == 'validator' else getattr(self, target)
                    record[key] = value
                    with self.assertRaises(ValueError):
                        self.invoke()

    def test_valid_chain_is_evidence_only(self):
        result = self.invoke()
        self.assertEqual(result['commit'], 'c' * 40)
        self.assertEqual(result['file_count'], 1)
        self.assertTrue(result['review_required'])
        self.assertTrue(result['candidate_import_verified'])
        for key in ('turn_bound', 'runtime_state_observed', 'production_accepted', 'resume_available'):
            self.assertIs(result[key], False)

    def test_manifest_or_blob_mismatch_rejected(self):
        for key, value in (('manifest_sha256', '0' * 64), ('blobs', {next(iter(self.blobs)): b'wrong'})):
            with self.subTest(key=key):
                packet = self.packet()
                packet[key] = value
                with self.assertRaises(ValueError):
                    bind_candidate(**packet)

    def test_dispatch_identity_stop_and_success_rejected(self):
        original = copy.deepcopy(self.dispatch)
        for key, value in (('sandbox_id', 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'),
                           ('image_id', 'sha256:' + '0' * 64), ('returncode', False),
                           ('returncode', 1), ('phase', 'running'), ('validation_vm_stopped', False),
                           ('manifest_sha256', '0' * 64), ('validation_passed', True)):
            with self.subTest(key=key, value=value):
                self.dispatch = dict(original, **{key: value})
                with self.assertRaises(ValueError):
                    self.invoke()

    def test_failed_or_unexecuted_tests_rejected(self):
        original = copy.deepcopy(self.summary['receipt']['test'])
        for key, value in (('returncode', 1), ('returncode', False), ('reported_test_count', 0),
                           ('reported_test_count', True), ('reason', 'timeout')):
            with self.subTest(key=key):
                self.summary['receipt']['test'] = dict(original, **{key: value})
                with self.assertRaises(ValueError):
                    self.invoke()

    def test_saved_summary_type_changes_rejected(self):
        packet = self.packet()
        dispatch = json.loads(packet['dispatch_raw'])
        dispatch['runner_summary']['receipt']['test']['returncode'] = False
        packet['dispatch_raw'] = encode(dispatch)
        with self.assertRaises(ValueError):
            bind_candidate(**packet)

    def test_each_raw_hash_link_required(self):
        for raw_key, field in (('dispatch_raw', 'stdout_sha256'),
                               ('build_raw', 'validation_dispatch_sha256'),
                               ('import_raw', 'origin_receipt_sha256')):
            with self.subTest(raw_key=raw_key):
                packet = self.packet()
                value = json.loads(packet[raw_key])
                value[field] = '0' * 64
                packet[raw_key] = encode(value)
                with self.assertRaises(ValueError):
                    bind_candidate(**packet)

    def test_distinct_container_ids_required(self):
        for identity in ('2' * 64, '4' * 64):
            with self.subTest(identity=identity):
                self.imported['container_evidence']['container_id'] = identity
                with self.assertRaises(ValueError):
                    self.invoke()

    def test_build_and_import_cleanup_and_boundary_required(self):
        for name in ('build', 'imported'):
            record = getattr(self, name)
            for key in ('all_vms_stopped', 'published', 'production_accepted'):
                with self.subTest(record=name, key=key):
                    old = record[key]
                    record[key] = not old
                    with self.assertRaises(ValueError):
                        self.invoke()
                    record[key] = old
            record['container_evidence']['boundary']['observations_verified'] = False
            with self.assertRaises(ValueError):
                self.invoke()
            record['container_evidence']['boundary']['observations_verified'] = True

    def test_parent_tree_commit_or_size_mismatch_rejected(self):
        original = copy.deepcopy(self.build['candidate'])
        for key, value in (('parent', '0' * 40), ('tree', '0' * 40), ('commit', 'bad'),
                           ('manifest_sha256', '0' * 64), ('bundle_bytes', True),
                           ('bundle_sha256', '0' * 64)):
            with self.subTest(key=key):
                self.build['candidate'] = dict(original, **{key: value})
                with self.assertRaises(ValueError):
                    self.invoke()

    def test_import_filecount_flags_and_commit_must_match(self):
        original = copy.deepcopy(self.imported['candidate'])
        for key, value in (('verified_file_count', True), ('verified_file_count', 2),
                           ('checked_out', True), ('source_executed', True),
                           ('import_verified', False), ('commit', '0' * 40)):
            with self.subTest(key=key):
                self.imported['candidate'] = dict(original, **{key: value})
                with self.assertRaises(ValueError):
                    self.invoke()

    def test_changed_bundle_rejected(self):
        packet = self.packet()
        packet['bundle'] += b'altered'
        with self.assertRaises(ValueError):
            bind_candidate(**packet)

    def test_partial_duplicate_nonfinite_receipts_rejected(self):
        for key in ('dispatch_raw', 'build_raw', 'import_raw'):
            for raw in (b'{', b'{"schema":1,"schema":1}', b'{"schema":1,"x":NaN}'):
                with self.subTest(key=key, raw=raw):
                    packet = self.packet()
                    packet[key] = raw
                    with self.assertRaises(ValueError):
                        bind_candidate(**packet)


class TurnCandidateBindingTests(unittest.TestCase):
    container = CandidateEvidenceBindingTests.container
    packet = CandidateEvidenceBindingTests.packet

    def setUp(self):
        CandidateEvidenceBindingTests.setUp(self)
        self.turn_binding = dict(turn_sha256='8' * 64, capture_sha256='9' * 64,
            operation_id='a' * 32, migration_epoch='dddddddd-dddd-4ddd-8ddd-dddddddddddd',
            sequence=4, role='machine', sandbox_id='eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee',
            manifest_sha256=self.digest, base='a' * 40)
        self.registration = dict(migration_epoch=self.turn_binding['migration_epoch'],
            roles={'machine': {'id': self.turn_binding['sandbox_id']},
                   'stdlib': {'id': 'ffffffff-ffff-4fff-8fff-ffffffffffff'}})
        self.dispatch['turn_evidence'] = copy.deepcopy(self.turn_binding)

    def bind_turn(self):
        return bind_turn_candidate(self.turn_binding, self.registration, **self.packet())

    def test_turn_candidate_success_does_not_authorize_fence_release(self):
        result = self.bind_turn()
        self.assertTrue(result['turn_bound'])
        self.assertEqual(result['turn_binding'], self.turn_binding)
        self.assertEqual(result['turn_validation']['outcome'], 'test_command_succeeded')
        self.assertTrue(result['review_required'])
        for key in ('fence_release_authorized', 'resume_available', 'production_accepted',
                    'runtime_state_observed'):
            self.assertIs(result[key], False)

    def test_maintenance_dispatch_without_turn_evidence_rejected(self):
        del self.dispatch['turn_evidence']
        with self.assertRaises(ValueError):
            self.bind_turn()

    def test_other_role_epoch_vm_or_sequence_rejected(self):
        original = copy.deepcopy(self.turn_binding)
        for key, value in (('role', 'stdlib'), ('role', 'unknown'),
                           ('migration_epoch', 'cccccccc-cccc-4ccc-8ccc-cccccccccccc'),
                           ('sandbox_id', 'ffffffff-ffff-4fff-8fff-ffffffffffff'),
                           ('sequence', 5), ('sequence', True), ('sequence', 4.0)):
            with self.subTest(key=key, value=value):
                self.turn_binding = dict(original, **{key: value})
                with self.assertRaises(ValueError):
                    self.bind_turn()

    def test_registry_epoch_change_rejects_old_consistent_evidence(self):
        self.registration['migration_epoch'] = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc'
        with self.assertRaises(ValueError):
            self.bind_turn()

    def test_registry_vm_replacement_rejects_old_consistent_evidence(self):
        self.registration['roles']['machine']['id'] = 'ffffffff-ffff-4fff-8fff-ffffffffffff'
        with self.assertRaises(ValueError):
            self.bind_turn()

    def test_consistently_failed_turn_cannot_become_candidate(self):
        self.summary['receipt']['test']['returncode'] = 1
        self.summary['receipt']['test_command_succeeded'] = False
        self.dispatch.update(returncode=1, phase='inspection_required')
        with self.assertRaisesRegex(ValueError, 'Failed turn'):
            self.bind_turn()


if __name__ == '__main__':
    unittest.main()
