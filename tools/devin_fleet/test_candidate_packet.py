"""Synthetic candidate transport packets; no Git, VM, or module execution."""
import base64
import hashlib
import json
import unittest
from unittest.mock import patch

import candidate_packet as packets
from snapshot_git_tree import expected_tree
from test_snapshot_git_tree import snapshot


def sha(data):
    return hashlib.sha256(data).hexdigest()


class CandidatePacketTests(unittest.TestCase):
    def setUp(self):
        self.raw, self.digest, self.blobs = snapshot([('src/a.py', '100644', b'synthetic source\n')])
        self.bundle = b'synthetic parent bundle'
        self.ref = 'refs/heads/fleet/integration'
        self.modules = {name: '# inert synthetic module\n' for name in (
            'sandbox_snapshot_receiver', 'snapshot_git_tree', 'container_candidate_commit')}

    def build(self, **overrides):
        args = dict(raw=self.raw, digest=self.digest, blobs=self.blobs,
                    parent_bundle=self.bundle, parent_bundle_sha256=sha(self.bundle),
                    parent_ref=self.ref, modules=self.modules)
        args.update(overrides)
        return packets.prepare_build(**args)

    def test_packet_preserves_exact_bytes_and_expected_tree(self):
        raw, expected = self.build()
        packet = json.loads(raw)
        self.assertIsInstance(raw, bytes)
        self.assertEqual(expected, expected_tree(self.raw, self.digest, self.blobs))
        self.assertEqual(base64.b64decode(packet['manifest']), self.raw)
        self.assertEqual({k: base64.b64decode(v) for k, v in packet['blobs'].items()}, self.blobs)
        self.assertEqual(base64.b64decode(packet['parent_bundle']), self.bundle)
        self.assertEqual(packet['parent_bundle_sha256'], sha(self.bundle))
        self.assertEqual(packet['parent_ref'], self.ref)
        self.assertEqual(packet['modules'], self.modules)

    def test_other_snapshot_base_and_safe_ref_are_not_fixed_to_stdlib(self):
        raw, _, blobs = snapshot([('lib/b.dat', '100755', b'\x00different\xff')])
        manifest = json.loads(raw)
        manifest['base'] = 'b' * 40
        raw = json.dumps(manifest, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
        payload, expected = self.build(raw=raw, digest=sha(raw), blobs=blobs,
                                       parent_ref='refs/heads/feature/another-1')
        self.assertEqual(expected['base'], 'b' * 40)
        self.assertEqual(json.loads(payload)['parent_ref'], 'refs/heads/feature/another-1')
        self.assertEqual(expected, expected_tree(raw, sha(raw), blobs))

    def test_snapshot_digest_or_blob_tampering_rejected(self):
        for overrides in ({'digest': '0' * 64}, {'blobs': {}},
                          {'blobs': {key: b'altered' for key in self.blobs}}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                self.build(**overrides)

    def test_parent_bundle_must_be_bounded_exact_bytes_with_matching_digest(self):
        for value in (b'', 'not bytes', b'x' * (16 * 1024 * 1024 + 1)):
            with self.subTest(kind=type(value).__name__, size=len(value)), self.assertRaises(ValueError):
                self.build(parent_bundle=value)
        with self.assertRaises(ValueError):
            self.build(parent_bundle_sha256='0' * 64)

    def test_exact_module_names_and_bounded_strings_required(self):
        missing = dict(self.modules)
        missing.pop('snapshot_git_tree')
        for modules in (missing, dict(self.modules, extra='code'),
                        dict(self.modules, snapshot_git_tree=b'not text'),
                        dict(self.modules, snapshot_git_tree='x' * 32769)):
            with self.subTest(keys=list(modules)), self.assertRaises(ValueError):
                self.build(modules=modules)

    def test_unsafe_or_non_head_refs_rejected(self):
        for ref in ('HEAD', 'refs/tags/v1', 'refs/heads/', '-option',
                    'refs/heads/a b', 'refs/heads/a\nb', 'refs/heads/a:other',
                    'refs/heads/../other', 'refs/heads/a.lock', 'refs/heads/a//b'):
            with self.subTest(ref=ref), self.assertRaises(ValueError):
                self.build(parent_ref=ref)

    def import_fixture(self):
        packet, expected = self.build()
        bundle = b'synthetic candidate bundle'
        metadata = dict(commit='c' * 40, parent=expected['base'], tree=expected['tree'],
            manifest_sha256=self.digest, bundle_sha256=sha(bundle), bundle_bytes=len(bundle),
            production_accepted=False, published=False)
        return packet, bundle, metadata

    def test_import_preserves_snapshot_and_adds_verified_bundle_metadata(self):
        original, bundle, metadata = self.import_fixture()
        result = json.loads(packets.prepare_import(original, bundle, metadata))
        for key, value in json.loads(original).items():
            self.assertEqual(result[key], value)
        self.assertIs(result['verify_import'], True)
        self.assertEqual(result['candidate_metadata'], metadata)
        self.assertEqual(base64.b64decode(result['candidate_bundle']), bundle)

    def test_import_metadata_must_match_snapshot_and_nonpublication_contract(self):
        original, bundle, metadata = self.import_fixture()
        for key, value in (('parent', '0' * 40), ('tree', '0' * 40), ('manifest_sha256', '0' * 64),
                           ('commit', 'invalid'), ('production_accepted', True), ('published', True),
                           ('bundle_bytes', True), ('bundle_bytes', len(bundle) + 1),
                           ('bundle_sha256', '0' * 64)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                packets.prepare_import(original, bundle, dict(metadata, **{key: value}))
        with self.assertRaises(ValueError):
            packets.prepare_import(original, bundle, dict(metadata, extra=True))

    def test_import_rechecks_original_snapshot_and_parent_bundle(self):
        original, bundle, metadata = self.import_fixture()
        decoded = json.loads(original)
        for changes in ({'digest': '0' * 64}, {'blobs': {}}, {'parent_bundle_sha256': '0' * 64},
                        {'modules': {}}, {'parent_ref': 'HEAD'}):
            modified = dict(decoded, **changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                packets.prepare_import(json.dumps(modified).encode(), bundle, metadata)

    def test_import_duplicate_keys_and_nonoriginal_packet_rejected(self):
        original, bundle, metadata = self.import_fixture()
        duplicate = b'{"digest":"bad",' + original[1:]
        for packet in (duplicate, b'{', b'[]', b'', 'not bytes',
                       json.dumps(dict(json.loads(original), verify_import=True)).encode()):
            with self.subTest(kind=type(packet).__name__), self.assertRaises(ValueError):
                packets.prepare_import(packet, bundle, metadata)

    def test_import_bundle_tampering_empty_or_oversize_rejected(self):
        original, bundle, metadata = self.import_fixture()
        for changed in (b'', bundle + b'changed', b'x' * (16 * 1024 * 1024 + 1)):
            with self.subTest(size=len(changed)), self.assertRaises(ValueError):
                packets.prepare_import(original, changed, metadata)

    def test_module_byte_limit_and_nonempty_are_enforced(self):
        for source in ('', '\u65e5' * 12000):
            with self.subTest(length=len(source)), self.assertRaises(ValueError):
                self.build(modules=dict(self.modules, snapshot_git_tree=source))
        self.build(modules=dict(self.modules, snapshot_git_tree='x' * 32768))

    def test_build_serialized_packet_limit(self):
        original, _ = self.build()
        with patch.object(packets, 'MAX_PACKET', len(original) - 1):
            with self.assertRaisesRegex(ValueError, 'Oversize'):
                self.build()

    def test_import_checks_expanded_packet_size_not_only_input(self):
        original, bundle, metadata = self.import_fixture()
        with patch.object(packets, 'MAX_PACKET', len(original)):
            with self.assertRaisesRegex(ValueError, 'Oversize'):
                packets.prepare_import(original, bundle, metadata)


if __name__ == '__main__':
    unittest.main()
