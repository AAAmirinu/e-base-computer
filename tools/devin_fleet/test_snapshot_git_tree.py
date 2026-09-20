"""Pure content-binding checks; no subprocess, Git, or source execution."""
import hashlib
import json
import unittest

from snapshot_git_tree import expected_tree, object_id, verify_commit_tree


def snapshot(files):
    blobs, entries = {}, []
    for path, mode, data in sorted(files):
        digest = hashlib.sha256(data).hexdigest()
        blobs[digest] = data
        entries.append(dict(path=path, mode=mode, sha256=digest, size=len(data)))
    raw = json.dumps(dict(schema=1, base='a'*40, files=entries),
                     sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    return raw, hashlib.sha256(raw).hexdigest(), blobs


class TreeTests(unittest.TestCase):
    def test_verifier_rejects_other_formats_and_tree_mismatch(self):
        args = snapshot([('x', '100644', b'a')])
        tree = expected_tree(*args)['tree']
        self.assertTrue(verify_commit_tree(*args, observed_format='sha1', observed_tree=tree)['tree_verified'])
        for fmt, oid in [('sha256', tree), ('sha1', '0'*40), ('sha1', tree.upper()), ('sha1', None)]:
            with self.subTest(fmt=fmt, oid=oid), self.assertRaises(ValueError):
                verify_commit_tree(*args, observed_format=fmt, observed_tree=oid)

    def test_empty_tree_known_git_identity(self):
        result = expected_tree(*snapshot([]))
        self.assertEqual(result['tree'], '4b825dc642cb6eb9a060e54bf8d69288fbee4904')
        self.assertFalse(result['committed'])
        self.assertFalse(result['production_accepted'])

    def test_known_blob(self):
        self.assertEqual(object_id(b'blob', b'test content\n').hex(),
                         'd670460b4b4aece5915caf5c68d12f560a9fe3e4')

    def test_mode_bytes_and_path_each_change_tree(self):
        baseline = [('x', '100644', b'hello\n')]
        original = expected_tree(*snapshot(baseline))['tree']
        for files in ([('x', '100755', b'hello\n')], [('x', '100644', b'hello\r\n')],
                      [('y', '100644', b'hello\n')], [('d/x', '100644', b'hello\n')]):
            self.assertNotEqual(expected_tree(*snapshot(files))['tree'], original)

    def test_directory_sort_uses_trailing_slash(self):
        data = b'a'
        blob = object_id(b'blob', data)
        subtree = object_id(b'tree', b'100644 x\0' + blob)
        payload = b'100644 a.c\0' + blob + b'40000 a\0' + subtree + b'100644 a0\0' + blob
        actual = expected_tree(*snapshot([('a/x', '100644', data),
                                          ('a.c', '100644', data), ('a0', '100644', data)]))
        self.assertEqual(actual['tree'], object_id(b'tree', payload).hex())

    def test_unicode_name_and_binary_blob(self):
        data = b'\0\xff\r\n'
        expected = object_id(b'tree', b'100644 ' + '日本語'.encode() + b'\0' + object_id(b'blob', data))
        self.assertEqual(expected_tree(*snapshot([('日本語', '100644', data)]))['tree'], expected.hex())

    def test_invalid_snapshot_not_accepted(self):
        raw, digest, blobs = snapshot([('x', '100644', b'a')])
        with self.assertRaises(ValueError):
            expected_tree(raw, '0'*64, blobs)
        with self.assertRaises(ValueError):
            expected_tree(raw, digest, {})


if __name__ == '__main__':
    unittest.main()
