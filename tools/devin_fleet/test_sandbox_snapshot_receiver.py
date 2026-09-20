"""Trusted synthetic source transport tests; no source execution."""
import copy
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

import sandbox_snapshot_receiver as receiver


class ReceiverTests(unittest.TestCase):
    def setUp(self):
        self.data = b'not executed\x00\xff'
        self.sha = hashlib.sha256(self.data).hexdigest()
        self.blobs = {self.sha: self.data}
        self.manifest = {'schema': 1, 'base': 'a' * 40, 'files': [
            {'path': 'src/example', 'mode': '100755', 'sha256': self.sha, 'size': len(self.data)}]}

    def raw(self):
        return json.dumps(self.manifest, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()

    def validate(self):
        raw = self.raw()
        return receiver.validate_snapshot(raw, hashlib.sha256(raw).hexdigest(), self.blobs)

    def test_valid_binary_and_dedup(self):
        second = dict(self.manifest['files'][0], path='z')
        self.manifest['files'].append(second)
        self.assertEqual(self.validate(), self.manifest)

    def test_bad_digest(self):
        with self.assertRaises(ValueError):
            receiver.validate_snapshot(self.raw(), 'b' * 64, self.blobs)

    def test_bad_raw(self):
        for raw in (b'\xff', b'{"schema":1,"schema":1}', b'{"a":NaN}', b'{"a":1.5}', b'[]'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                receiver.validate_snapshot(raw, hashlib.sha256(raw).hexdigest(), {})

    def test_noncanonical(self):
        raw = json.dumps(self.manifest).encode()
        with self.assertRaises(ValueError):
            receiver.validate_snapshot(raw, hashlib.sha256(raw).hexdigest(), self.blobs)

    def test_escaped_surrogate_reaches_receiver(self):
        self.manifest['files'][0]['path'] = '\ud800'
        raw = json.dumps(self.manifest, ensure_ascii=True).encode('ascii')
        with self.assertRaises(ValueError):
            receiver.validate_snapshot(raw, hashlib.sha256(raw).hexdigest(), self.blobs)

    def test_empty_file_and_empty_manifest(self):
        digest = hashlib.sha256(b'').hexdigest()
        self.manifest['files'][0].update(sha256=digest, size=0)
        self.blobs = {digest: b''}
        self.validate()
        self.manifest['files'] = []
        self.blobs = {}
        self.validate()

    def test_exact_schema(self):
        for key, value in [('schema', True), ('schema', 2), ('base', 'A' * 40), ('files', {}), ('extra', 1)]:
            original = copy.deepcopy(self.manifest)
            self.manifest[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.validate()
            self.manifest = original

    def test_bad_paths(self):
        for path in ('/a', '../a', 'a/../b', 'a//b', './a', 'a/', 'a\\b', 'c:a',
                     'a\0b', 'a\nb', '.git/config', 'a/.DEVIN/x', '.fleet/x',
                     'private_materials/x', '.env', 'a' * 256, '/'.join(['a'] * 129), '\ud800'):
            self.manifest['files'][0]['path'] = path
            with self.subTest(path=repr(path)), self.assertRaises((ValueError, UnicodeError)):
                self.validate()

    def test_duplicates_order_and_ancestor_collision(self):
        for paths in (('a', 'a'), ('z', 'a'), ('a', 'a/b'), ('a/b', 'a/b/c')):
            template = self.manifest['files'][0]
            self.manifest['files'] = [dict(template, path=p) for p in paths]
            with self.subTest(paths=paths), self.assertRaises(ValueError):
                self.validate()

    def test_bad_metadata(self):
        for key, value in [('mode', '120000'), ('mode', 100644), ('size', True), ('size', -1),
                           ('size', receiver.MAX_FILE + 1), ('sha256', '../blob'), ('extra', 1)]:
            original = copy.deepcopy(self.manifest)
            self.manifest['files'][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.validate()
            self.manifest = original

    def test_missing_extra_corrupt_and_wrong_type_blobs(self):
        for blobs in ({}, {**self.blobs, '0' * 64: b''}, {self.sha: b'corrupt'}, {self.sha: bytearray(self.data)}):
            self.blobs = blobs
            with self.assertRaises(ValueError):
                self.validate()

    def test_limits(self):
        for name, limit in [('MAX_MANIFEST', 4), ('MAX_FILES', 0), ('MAX_TOTAL', 0)]:
            with patch.object(receiver, name, limit), self.assertRaises(ValueError):
                self.validate()

    def test_expanded_size_counts_duplicate_content(self):
        self.manifest['files'].append(dict(self.manifest['files'][0], path='z'))
        with patch.object(receiver, 'MAX_TOTAL', len(self.data)), self.assertRaises(ValueError):
            self.validate()

    def test_conflicting_sizes(self):
        self.manifest['files'].append(dict(self.manifest['files'][0], path='z', size=0))
        with self.assertRaises(ValueError):
            self.validate()

    @unittest.skipUnless(sys.platform == 'linux', 'Linux guest only')
    def test_materialize_modes_bytes_no_links_and_no_reuse(self):
        self.manifest['files'].append(dict(self.manifest['files'][0], path='z', mode='100644'))
        with tempfile.TemporaryDirectory() as parent:
            raw = self.raw()
            digest = hashlib.sha256(raw).hexdigest()
            result = receiver.materialize_snapshot(parent, 'source', raw, digest, self.blobs)
            root = Path(parent) / 'source'
            self.assertEqual((root / 'src/example').read_bytes(), self.data)
            self.assertEqual(stat.S_IMODE((root / 'src/example').stat().st_mode), 0o755)
            self.assertEqual(stat.S_IMODE((root / 'z').stat().st_mode), 0o644)
            self.assertNotEqual((root / 'z').stat().st_ino, (root / 'src/example').stat().st_ino)
            self.assertFalse(result['source_executed'])
            with self.assertRaises(FileExistsError):
                receiver.materialize_snapshot(parent, 'source', raw, digest, self.blobs)

    @unittest.skipUnless(sys.platform == 'linux', 'Linux guest only')
    def test_symlink_parent_and_unsafe_name_refused(self):
        raw = self.raw()
        digest = hashlib.sha256(raw).hexdigest()
        with tempfile.TemporaryDirectory() as parent:
            target = Path(parent) / 'target'
            target.mkdir()
            (Path(parent) / 'link').symlink_to(target, target_is_directory=True)
            with self.assertRaises(OSError):
                receiver.materialize_snapshot(str(Path(parent) / 'link'), 'source', raw, digest, self.blobs)
            for name in ('../escape', '.hidden', 'a/b'):
                with self.assertRaises(ValueError):
                    receiver.materialize_snapshot(parent, name, raw, digest, self.blobs)
            self.assertEqual(list(target.iterdir()), [])

    @unittest.skipUnless(sys.platform == 'linux', 'Linux guest only')
    def test_failure_retains_partial_without_receipt(self):
        raw = self.raw()
        with tempfile.TemporaryDirectory() as parent:
            with patch.object(receiver.os, 'write', side_effect=OSError('injected')):
                with self.assertRaises(OSError):
                    receiver.materialize_snapshot(parent, 'source', raw, hashlib.sha256(raw).hexdigest(), self.blobs)
            self.assertTrue((Path(parent) / 'source/src/example').exists())

    @unittest.skipUnless(sys.platform == 'linux', 'Linux guest only')
    def test_partial_write_retried(self):
        raw = self.raw()
        original_write = os.write
        def short_write(fd, data):
            return original_write(fd, data[:2])
        with tempfile.TemporaryDirectory() as parent:
            with patch.object(receiver.os, 'write', side_effect=short_write):
                receiver.materialize_snapshot(parent, 'source', raw, hashlib.sha256(raw).hexdigest(), self.blobs)
            self.assertEqual((Path(parent) / 'source/src/example').read_bytes(), self.data)


if __name__ == '__main__':
    unittest.main()
