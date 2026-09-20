import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from validation_snapshot_input import load_snapshot, digest_argument, load_capture


class SnapshotInputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'blobs').mkdir(mode=0o700)
        self.blob = hashlib.sha256(b'hello').hexdigest()
        self.manifest = {'schema': 1, 'base': 'a' * 40, 'files': [
            {'path': 'source.py', 'size': 5, 'mode': '100644', 'sha256': self.blob}]}
        self.raw = json.dumps(self.manifest, sort_keys=True, separators=(',', ':')).encode()
        self.digest = hashlib.sha256(self.raw).hexdigest()
        (self.root / 'manifest.json').write_bytes(self.raw)
        (self.root / 'blobs' / self.blob).write_bytes(b'hello')

    def test_loads_verified_data_only(self):
        raw, blobs, manifest = load_snapshot(self.root, self.digest)
        self.assertEqual(raw, self.raw)
        self.assertEqual(blobs, {self.blob: b'hello'})
        self.assertEqual(manifest, self.manifest)

    def test_wrong_hash_refused_before_blob_reads(self):
        import validation_snapshot_input as module
        original = module._file
        with patch.object(module, '_file', wraps=original) as read, self.assertRaises(ValueError):
            load_snapshot(self.root, '0' * 64)
        self.assertEqual(read.call_count, 1)

    def test_extra_blob_refused(self):
        (self.root / 'blobs' / 'unexpected').write_bytes(b'private')
        with self.assertRaises(ValueError):
            load_snapshot(self.root, self.digest)

    def test_missing_blob_refused(self):
        (self.root / 'blobs' / self.blob).unlink()
        with self.assertRaises(ValueError):
            load_snapshot(self.root, self.digest)

    def test_corrupt_blob_refused(self):
        (self.root / 'blobs' / self.blob).write_bytes(b'bad')
        with self.assertRaises(ValueError):
            load_snapshot(self.root, self.digest)

    def test_digest_shape(self):
        for value in ('A' * 64, '', '../file', None):
            with self.assertRaises(ValueError):
                digest_argument(value)

    def test_capture_provenance_and_mutations(self):
        snapshot = self.root / 'source-snapshot'
        record = {'schema': 1, 'role': 'stdlib', 'sandbox_id': 'vm', 'base': self.manifest['base'],
            'manifest_sha256': self.digest, 'snapshot_directory': str(snapshot), 'source_executed': False,
            'source_vm_stopped': True, 'source_checkpoint': {'base': self.manifest['base'],
                'changed': ['source.py'], 'fingerprints': {'source.py': self.blob}},
            'file_count': 1, 'blob_count': 1, 'source_bytes': 5}
        path = self.root / 'capture.json'
        path.write_text(json.dumps(record))
        result = load_capture(path, snapshot, self.digest, self.manifest, {'stdlib': {'id': 'vm'}})
        self.assertEqual(result['capture_sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
        for key, bad in [('role', 'other'), ('sandbox_id', 'other'), ('base', '0' * 40),
                         ('manifest_sha256', '0' * 64), ('source_vm_stopped', False),
                         ('snapshot_directory', '/other'), ('file_count', True), ('source_bytes', 6)]:
            invalid = dict(record, **{key: bad})
            path.write_text(json.dumps(invalid))
            with self.subTest(key=key), self.assertRaises(ValueError):
                load_capture(path, snapshot, self.digest, self.manifest, {'stdlib': {'id': 'vm'}})

    def test_capture_fingerprint_mismatch(self):
        record = {'schema': 1, 'role': 'stdlib', 'sandbox_id': 'vm', 'base': self.manifest['base'],
            'manifest_sha256': self.digest, 'snapshot_directory': str(self.root / 'source-snapshot'),
            'source_executed': False, 'source_vm_stopped': True, 'source_checkpoint': {
                'base': self.manifest['base'], 'changed': ['source.py'], 'fingerprints': {'source.py': '0' * 64}}}
        path = self.root / 'capture.json'
        path.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, 'fingerprint mismatch'):
            load_capture(path, self.root / 'source-snapshot', self.digest, self.manifest, {'stdlib': {'id': 'vm'}})


if __name__ == '__main__':
    unittest.main()
