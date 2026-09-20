"""Source snapshot contract tests; fake repositories, no process execution."""
import hashlib
import json
import copy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import fleet
import sandbox_snapshot
from sandbox_snapshot import capture_source_snapshot, persist_source_snapshot


BASE = 'a' * 40


class FakeRepository:
    def __init__(self):
        self.tracked = 'src/a.py\0'
        self.untracked = ''
        self.files = {'src/a.py': {'mode': '100644', 'data': b'hello\n'}}
        self.kinds = {}
        self.calls = []
        self.controller = SimpleNamespace(stop=Mock())

    def git(self, *args):
        self.calls.append(('git', args))
        if args == ('ls-files', '-z'):
            return self.tracked
        if args == ('ls-files', '--others', '--exclude-standard', '-z'):
            return self.untracked
        raise AssertionError('Unexpected Git operation: ' + repr(args))

    def path_kind(self, path):
        self.calls.append(('kind', path))
        return self.kinds.get(path, 'regular' if path in self.files else 'missing')

    def snapshot_file(self, path, *, max_bytes):
        self.calls.append(('read', path, max_bytes))
        value = self.files[path]
        if len(value['data']) > max_bytes:
            raise ValueError('snapshot file exceeds bound')
        return dict(value)


class SourceSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.repo = FakeRepository()
        self.expected = {'base': BASE, 'changed': [], 'fingerprints': {}}
        self.sha = self.enterContext(patch.object(fleet, 'sha', return_value=BASE))
        self.changes = self.enterContext(patch.object(fleet, 'changes', return_value=[]))
        self.fingerprints = self.enterContext(patch.object(fleet, 'fingerprints', return_value={}))

    def capture(self):
        return capture_source_snapshot(self.repo, self.expected)

    def test_deterministic_sorted_union_binary_modes_and_blob_dedup(self):
        payload = b'\x00\xff\r\n'
        self.repo.tracked = 'z\0src/a.py\0'
        self.repo.untracked = 'u\0z\0'
        self.repo.files.update({'z': {'mode': '100755', 'data': payload},
                                'u': {'mode': '100644', 'data': payload}})
        result = self.capture()
        entries = result['manifest']['files']
        self.assertEqual([entry['path'] for entry in entries], ['src/a.py', 'u', 'z'])
        self.assertEqual([entry['mode'] for entry in entries], ['100644', '100644', '100755'])
        self.assertEqual(result['manifest']['base'], BASE)
        self.assertEqual(result['manifest']['schema'], 1)
        self.assertEqual(len(result['blobs']), 2)
        for entry in entries:
            data = self.repo.files[entry['path']]['data']
            digest = hashlib.sha256(data).hexdigest()
            self.assertEqual(entry['sha256'], digest)
            self.assertEqual(entry['size'], len(data))
            self.assertEqual(result['blobs'][digest], data)
        canonical = json.dumps(result['manifest'], sort_keys=True, separators=(',', ':'),
                               ensure_ascii=False).encode('utf-8')
        self.assertEqual(result['manifest_sha256'], hashlib.sha256(canonical).hexdigest())
        self.assertEqual([item for item in self.repo.calls if item[0] == 'git'], [
            ('git', ('ls-files', '-z')),
            ('git', ('ls-files', '--others', '--exclude-standard', '-z')),
            ('git', ('ls-files', '-z'))])
        self.assertEqual(self.sha.call_count, 2)
        self.assertEqual(self.changes.call_count, 2)
        self.assertEqual(self.fingerprints.call_count, 2)

    def test_tracked_deletion_is_omitted(self):
        self.repo.tracked += 'deleted.py\0'
        result = self.capture()
        self.assertEqual([x['path'] for x in result['manifest']['files']], ['src/a.py'])
        self.assertNotIn(('read', 'deleted.py', 1048576), self.repo.calls)

    def test_untracked_control_directory_is_excluded_without_read(self):
        self.repo.untracked = '.fleet/prompt.md\0'
        self.capture()
        self.assertFalse(any('.fleet/prompt.md' in call for call in self.repo.calls))

    def test_tracked_control_directory_rejected(self):
        self.repo.tracked = '.fleet/config.json\0'
        with self.assertRaises(Exception):
            self.capture()

    def test_forbidden_paths_rejected_for_tracked_and_untracked(self):
        for name in ['.git/config', 'src/.git/config', '.devin/key', 'src/.devin/key',
                     'private_materials/notes.md', '.env']:
            for listing in ['tracked', 'untracked']:
                with self.subTest(name=name, listing=listing):
                    self.repo = FakeRepository()
                    setattr(self.repo, listing, name + '\0')
                    with self.assertRaises(Exception):
                        self.capture()

    def test_malformed_paths_and_nul_lists_rejected(self):
        for text in ['a', '\0', 'a\0\0', '/abs\0', '../escape\0', 'a/../b\0',
                     './a\0', 'a//b\0', 'a/\0', 'a\\b\0']:
            with self.subTest(text=text):
                self.repo.tracked = text
                with self.assertRaises(Exception):
                    self.capture()

    def test_unsafe_kinds_rejected_without_read(self):
        for kind in ['symlink', 'hardlink', 'directory', 'other', 'fifo', 'unknown']:
            with self.subTest(kind=kind):
                self.repo = FakeRepository()
                self.repo.kinds['src/a.py'] = kind
                with self.assertRaises(Exception):
                    self.capture()
                self.assertFalse(any(call[0] == 'read' for call in self.repo.calls))

    def test_before_state_mismatch_rejected_before_reads(self):
        for helper, value in [(self.sha, 'b' * 40), (self.changes, ['new']),
                              (self.fingerprints, {'new': 'c' * 64})]:
            with self.subTest(helper=helper):
                previous = helper.return_value
                helper.return_value = value
                self.repo.calls.clear()
                with self.assertRaises(Exception):
                    self.capture()
                self.assertFalse(any(call[0] == 'read' for call in self.repo.calls))
                helper.return_value = previous

    def test_after_state_mutation_rejected(self):
        for helper, before, after in [(self.sha, BASE, 'b' * 40),
                                      (self.changes, [], ['new']),
                                      (self.fingerprints, {}, {'new': 'c' * 64})]:
            with self.subTest(helper=helper):
                helper.side_effect = [before, after]
                with self.assertRaises(Exception):
                    self.capture()
                helper.side_effect = None

    def test_invalid_file_mode_or_payload_rejected(self):
        for value in [{'mode': '120000', 'data': b'x'},
                      {'mode': '100644', 'data': 'text'}]:
            with self.subTest(value=value):
                self.repo.files['src/a.py'] = value
                with self.assertRaises(Exception):
                    self.capture()

    def test_file_limit_is_one_mebibyte(self):
        self.repo.files['src/a.py']['data'] = b'x' * 1048576
        self.capture()
        self.assertIn(('read', 'src/a.py', 1048576), self.repo.calls)
        self.repo.files['src/a.py']['data'] += b'x'
        with self.assertRaises(Exception):
            self.capture()

    def test_total_byte_limit_counts_duplicate_content(self):
        self.repo.tracked = ''.join(f'f{i:02}\0' for i in range(17))
        self.repo.files = {f'f{i:02}': {'mode': '100644', 'data': b'x' * 1048576}
                           for i in range(17)}
        with self.assertRaises(Exception):
            self.capture()

    def test_file_count_limit(self):
        self.repo.tracked = ''.join(f'f{i}\0' for i in range(2049))
        self.repo.files = {f'f{i}': {'mode': '100644', 'data': b''} for i in range(2049)}
        with self.assertRaises(Exception):
            self.capture()

    def test_tracked_inventory_mutation_rejected(self):
        original = self.repo.git
        queries = 0

        def git(*args):
            nonlocal queries
            if args == ('ls-files', '-z'):
                queries += 1
                if queries == 2:
                    return 'other.py\0'
            return original(*args)

        self.repo.git = git
        with self.assertRaises(RuntimeError):
            self.capture()

    def test_missing_untracked_file_rejected(self):
        self.repo.untracked = 'vanished.py\0'
        with self.assertRaises(RuntimeError):
            self.capture()

    def test_duplicate_inventory_entry_rejected(self):
        self.repo.tracked = 'src/a.py\0src/a.py\0'
        with self.assertRaises(ValueError):
            self.capture()


class PersistSourceSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.output = self.root / 'snapshot'
        self.data = b'\x00\xff inert executable-source bytes\n'
        self.digest = hashlib.sha256(self.data).hexdigest()
        self.snapshot = {'manifest': {'schema': 1, 'base': BASE, 'files': [
            {'path': 'nested/実行.py', 'mode': '100755', 'sha256': self.digest,
             'size': len(self.data)}]}, 'blobs': {self.digest: self.data}}
        self.rehash()

    def rehash(self):
        canonical = json.dumps(self.snapshot['manifest'], sort_keys=True,
                               separators=(',', ':'), ensure_ascii=False).encode('utf-8')
        self.snapshot['manifest_sha256'] = hashlib.sha256(canonical).hexdigest()
        return canonical

    def test_writes_hash_named_inert_blobs_and_canonical_manifest_only(self):
        before = copy.deepcopy(self.snapshot)
        canonical = self.rehash()
        persist_source_snapshot(self.output, self.snapshot)
        self.assertEqual(self.snapshot, before)
        self.assertEqual(sorted(p.name for p in self.output.iterdir()), ['blobs', 'manifest.json'])
        self.assertEqual([p.name for p in (self.output / 'blobs').iterdir()], [self.digest])
        self.assertEqual((self.output / 'blobs' / self.digest).read_bytes(), self.data)
        self.assertEqual((self.output / 'manifest.json').read_bytes(), canonical)
        manifest = json.loads((self.output / 'manifest.json').read_bytes())
        self.assertEqual(manifest['files'][0]['path'], 'nested/実行.py')
        self.assertEqual(manifest['files'][0]['mode'], '100755')
        self.assertFalse((self.output / 'nested').exists())

    def test_corrupt_manifest_rejected_before_directory_creation(self):
        self.snapshot['manifest']['base'] = 'b' * 40
        with self.assertRaises(ValueError):
            persist_source_snapshot(self.output, self.snapshot)
        self.assertFalse(self.output.exists())

    def test_corrupt_blob_rejected_before_directory_creation(self):
        self.snapshot['blobs'][self.digest] = b'corrupted'
        with self.assertRaises(ValueError):
            persist_source_snapshot(self.output, self.snapshot)
        self.assertFalse(self.output.exists())

    def test_corrupt_length_rejected_before_directory_creation(self):
        self.snapshot['manifest']['files'][0]['size'] += 1
        self.rehash()
        with self.assertRaises(ValueError):
            persist_source_snapshot(self.output, self.snapshot)
        self.assertFalse(self.output.exists())

    def test_missing_blob_rejected_before_directory_creation(self):
        self.snapshot['blobs'].clear()
        with self.assertRaises((KeyError, ValueError)):
            persist_source_snapshot(self.output, self.snapshot)
        self.assertFalse(self.output.exists())

    def test_existing_directory_refused_and_contents_preserved(self):
        self.output.mkdir()
        marker = self.output / 'marker'
        marker.write_bytes(b'preserve')
        with self.assertRaises(FileExistsError):
            persist_source_snapshot(self.output, self.snapshot)
        self.assertEqual(marker.read_bytes(), b'preserve')
        self.assertEqual([p.name for p in self.output.iterdir()], ['marker'])

    def test_blob_write_failure_never_publishes_manifest(self):
        with patch.object(sandbox_snapshot, '_atomic_bytes', side_effect=OSError('injected')) as write:
            with self.assertRaises(OSError):
                persist_source_snapshot(self.output, self.snapshot)
        write.assert_called_once_with(self.output / 'blobs' / self.digest, self.data)
        self.assertTrue(self.output.is_dir())
        self.assertFalse((self.output / 'manifest.json').exists())

    def test_relative_directory_rejected(self):
        with self.assertRaises(ValueError):
            persist_source_snapshot(Path('not-an-absolute-snapshot-directory'), self.snapshot)


if __name__ == '__main__':
    unittest.main()
