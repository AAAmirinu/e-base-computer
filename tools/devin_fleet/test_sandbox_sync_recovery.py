"""Trusted-driver recovery inspection contracts; no host Git or execution."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sandbox_sync_recovery import inspect_sync_recovery
from test_sandbox_sync import Runtime, OLD, BASE, EPOCH, MERGE


OPERATION = '1234567890abcdef' * 2


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.evidence = self.root / 'fresh-evidence'
        self.runtime = Runtime(self.root / 'unused-journal')
        self.commit_results = {OLD: OLD, BASE: BASE}
        self.receipt = {
            'schema': 2, 'migration_epoch': EPOCH, 'operation_id': OPERATION,
            'phase': 'applying', 'source_role': 'coordinator', 'target_role': 'machine',
            'source_id': 'source-uuid', 'target_id': 'target-uuid',
            'before': OLD, 'baseline': BASE, 'head_ref': 'HEAD',
            'guest_root': '/home/agent/workspace/machine',
            'transfer': {'source_role': 'coordinator', 'target_role': 'machine',
                         'source_id': 'source-uuid', 'target_id': 'target-uuid',
                         'commit': BASE, 'target_head': OLD, 'source_head': BASE,
                         'operation_id': 'd' * 32, 'bundle_sha256': 'e' * 64,
                         'bundle_bytes': 1024,
                         'relative': '.fleet/object-transfer-' + 'd' * 32 + '/objects.bundle',
                         'bundle_ref': 'refs/fleet-transfers/' + 'd' * 32}}
        for name in ('subprocess.run', 'subprocess.Popen', 'os.system'):
            guard = patch(name, side_effect=AssertionError('Host execution forbidden'))
            guard.start()
            self.addCleanup(guard.stop)

    def inspect(self, raw=None, **overrides):
        if raw is None:
            raw = json.dumps(self.receipt).encode('utf-8')
        args = dict(runtime=self.runtime, raw_receipt=raw,
                    expected_operation=OPERATION, evidence_directory=self.evidence)
        args.update(overrides)
        runtime = args['runtime']
        original_git = runtime.repo.git
        def git(*command):
            if len(command) == 3 and command[:2] == ('rev-parse', '--verify'):
                self.assertEqual(runtime.active, 'machine')
                runtime.events.append(command)
                self.assertTrue(command[2].endswith('^{commit}'))
                commit = command[2][:-len('^{commit}')]
                result = self.commit_results.get(commit)
                if result is None:
                    raise RuntimeError('Missing recorded commit')
                return result + '\n'
            return original_git(*command)
        with patch.object(runtime.repo, 'git', side_effect=git):
            return inspect_sync_recovery(**args)

    def saved(self):
        return json.loads((self.evidence / 'inspection.json').read_text(encoding='utf-8'))

    def assert_read_only(self):
        self.assertNotIn(MERGE, self.runtime.events)
        for event in self.runtime.events:
            self.assertIn(event[0], ('path_kind', 'rev-parse', 'status', 'merge-base'))
        self.assertEqual(self.runtime.leases, ['machine'])
        self.assertIsNone(self.runtime.active)

    def test_applying_at_baseline_verified_with_immutable_original(self):
        self.runtime.repo.head = BASE
        raw = json.dumps(self.receipt).encode('utf-8')
        original = self.root / 'original.json'
        original.write_bytes(raw)
        result = self.inspect(raw=raw)
        self.assertEqual(result, self.saved())
        self.assertEqual(result['phase'], 'inspected')
        self.assertEqual(result['outcome'], 'verified_applied')
        self.assertEqual(result['original_sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(result['operation_id'], OPERATION)
        self.assertEqual(result['migration_epoch'], EPOCH)
        self.assertIs(result['replay_permitted'], False)
        self.assertEqual(original.read_bytes(), raw)
        self.assertIn(('rev-parse', '--verify', OLD + '^{commit}'), self.runtime.events)
        self.assertIn(('rev-parse', '--verify', BASE + '^{commit}'), self.runtime.events)
        self.assertIn(('merge-base', OLD, BASE), self.runtime.events)
        self.assert_read_only()

    def test_missing_or_wrong_recorded_commit_cannot_verify_applied(self):
        for index, (commit, result) in enumerate(((OLD, None), (BASE, None),
                                                 (OLD, 'f' * 40), (BASE, 'f' * 40))):
            with self.subTest(commit=commit, result=result):
                self.evidence = self.root / ('commit-failure-' + str(index))
                self.runtime = Runtime(self.root / 'unused-journal')
                self.runtime.repo.head = BASE
                self.commit_results = {OLD: OLD, BASE: BASE}
                self.commit_results[commit] = result
                with self.assertRaises(RuntimeError):
                    self.inspect()
                self.assertEqual(self.saved()['phase'], 'checking')
                self.assertNotIn('outcome', self.saved())
                self.assert_read_only()

    def test_unrelated_recorded_before_cannot_verify_applied(self):
        self.runtime.repo.head = BASE
        self.runtime.repo.ancestor = 'f' * 40
        with self.assertRaises(RuntimeError):
            self.inspect()
        self.assertIn(('merge-base', OLD, BASE), self.runtime.events)
        self.assertEqual(self.saved()['phase'], 'checking')
        self.assertNotIn('outcome', self.saved())
        self.assert_read_only()

    def test_full_transfer_schema_required_before_lease(self):
        cases = []
        for key in self.receipt['transfer']:
            item = copy.deepcopy(self.receipt)
            del item['transfer'][key]
            cases.append(item)
        item = copy.deepcopy(self.receipt)
        item['transfer']['unexpected'] = 'metadata'
        cases.append(item)
        for key, values in {
                'source_head': (None, True, 'HEAD', 'A' * 40, 'a' * 39, 'g' * 40),
                'bundle_bytes': (None, True, False, 0, -1, 16 * 1024 * 1024 + 1, '1024', 1.0),
                'relative': ('../../wrong', '.fleet/object-transfer-' + 'f' * 32 + '/objects.bundle'),
                'bundle_ref': ('refs/heads/other', 'refs/fleet-transfers/' + 'f' * 32),
        }.items():
            for value in values:
                item = copy.deepcopy(self.receipt)
                item['transfer'][key] = value
                cases.append(item)
        for item in cases:
            with self.subTest(transfer=item['transfer']), self.assertRaises(ValueError):
                self.inspect(raw=json.dumps(item).encode('utf-8'))
            self.assertEqual(self.runtime.leases, [])
            self.assertFalse(self.evidence.exists())

    def test_transfer_size_bounds_accepted(self):
        for size in (1, 16 * 1024 * 1024):
            with self.subTest(size=size):
                self.evidence = self.root / ('size-' + str(size))
                self.runtime = Runtime(self.root / 'unused-journal')
                self.receipt['transfer']['bundle_bytes'] = size
                self.receipt['phase'] = 'transferred'
                self.assertEqual(self.inspect()['outcome'], 'pre_application')
                self.assert_read_only()

    def test_applying_at_before_requires_inspection_without_replay(self):
        result = self.inspect()
        self.assertEqual(result['outcome'], 'inspection_required')
        self.assertIs(result['replay_permitted'], False)
        self.assert_read_only()

    def test_transferred_at_before_is_pre_application(self):
        self.receipt['phase'] = 'transferred'
        self.assertEqual(self.inspect()['outcome'], 'pre_application')
        self.assert_read_only()

    def test_complete_no_op_verified(self):
        self.receipt.update(phase='complete', baseline=OLD, no_op=True)
        del self.receipt['transfer']
        self.assertEqual(self.inspect()['outcome'], 'verified_applied')
        self.assert_read_only()

    def test_unbound_receipts_rejected_before_evidence_or_lease(self):
        cases = []
        for key, values in {
                'schema': (1, True, '2'), 'migration_epoch': ('legacy', EPOCH.upper()),
                'operation_id': ('a' * 32, OPERATION.upper()),
                'source_id': ('other',), 'target_id': ('other',),
                'source_role': ('machine', 'unknown'), 'target_role': ('unknown',),
                'phase': ('unknown',), 'before': ('HEAD',),
                'guest_root': ('relative', '/', '/home/../tmp'),
                'head_ref': ('refs/tags/release',)}.items():
            for value in values:
                item = copy.deepcopy(self.receipt)
                item[key] = value
                cases.append(item)
        for key in self.receipt['transfer']:
            item = copy.deepcopy(self.receipt)
            item['transfer'][key] = 'wrong'
            cases.append(item)
        for key in ('migration_epoch', 'operation_id', 'transfer'):
            item = copy.deepcopy(self.receipt)
            del item[key]
            cases.append(item)
        for item in cases:
            with self.subTest(receipt=item), self.assertRaises(ValueError):
                self.inspect(raw=json.dumps(item).encode('utf-8'))
            self.assertFalse(self.evidence.exists())
            self.assertEqual(self.runtime.leases, [])

    def test_invalid_json_size_duplicates_and_nonfinite_refused_before_lease(self):
        raw = json.dumps(self.receipt).encode('utf-8')
        cases = (b'', b' ' * 65537, b'[]', b'\xff', raw.decode('utf-8'),
                 b'{"schema":2,' + raw[1:],
                 raw.replace(b'"schema": 2', b'"schema": NaN'),
                 raw.replace(b'"schema": 2', b'"schema": Infinity'),
                 raw.replace(b'"schema": 2', b'"schema": 1e999'))
        for invalid in cases:
            with self.subTest(raw_type=type(invalid), size=len(invalid)), self.assertRaises(ValueError):
                self.inspect(raw=invalid)
            self.assertEqual(self.runtime.leases, [])
            self.assertFalse(self.evidence.exists())

    def test_bad_expected_operation_rejected_before_lease(self):
        for value in (None, '', 'a' * 31, OPERATION.upper()):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.inspect(expected_operation=value)
            self.assertEqual(self.runtime.leases, [])
            self.assertFalse(self.evidence.exists())

    def test_nonfinite_transfer_metadata_refused_before_lease(self):
        raw = json.dumps(self.receipt).encode('utf-8')
        raw = raw.replace(b'"transfer": {', b'"transfer": {"bundle_bytes": 1e999,')
        with self.assertRaises(ValueError):
            self.inspect(raw=raw)
        self.assertEqual(self.runtime.leases, [])
        self.assertFalse(self.evidence.exists())

    def test_unsafe_live_state_retains_only_checking_evidence(self):
        changes = (('status', ' M important\x00'),
                   ('path_kinds', {'.git': 'directory', '.git/MERGE_HEAD': 'regular'}),
                   ('head_ref', 'refs/heads/other'),
                   ('guest_root', '/home/agent/workspace/other'), ('head', 'f' * 40))
        for index, (attribute, value) in enumerate(changes):
            with self.subTest(attribute=attribute):
                self.runtime = Runtime(self.root / 'unused-journal')
                self.evidence = self.root / ('failure-' + str(index))
                setattr(self.runtime.repo, attribute, value)
                with self.assertRaises(RuntimeError):
                    self.inspect()
                self.assertEqual(self.saved()['phase'], 'checking')
                self.assertNotIn('outcome', self.saved())
                self.assert_read_only()

    def test_stop_failure_never_finalizes_evidence(self):
        self.runtime.repo.head = BASE
        self.runtime.fail_exit_number = 1
        with self.assertRaisesRegex(RuntimeError, 'VM stop injected'):
            self.inspect()
        self.assertEqual(self.saved()['phase'], 'checking')
        self.assertNotIn('outcome', self.saved())
        self.assert_read_only()

    def test_existing_evidence_directory_refused_without_overwrite_or_lease(self):
        self.evidence.mkdir()
        sentinel = self.evidence / 'inspection.json'
        sentinel.write_bytes(b'previous evidence')
        with self.assertRaises(FileExistsError):
            self.inspect()
        self.assertEqual(sentinel.read_bytes(), b'previous evidence')
        self.assertEqual(self.runtime.leases, [])

    def test_relative_evidence_path_refused_before_lease(self):
        with self.assertRaises(ValueError):
            self.inspect(evidence_directory='relative')
        self.assertEqual(self.runtime.leases, [])


if __name__ == '__main__':
    unittest.main()
