"""Execute only synthetic dependency stubs through the trusted packet loader."""
import base64
import io
import json
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from run_stdlib_candidate import INNER


class CandidateInnerOrderTests(unittest.TestCase):
    def invoke(self, imported):
        modules = {
            'sandbox_snapshot_receiver': 'X = 7\n',
            'snapshot_git_tree': 'from sandbox_snapshot_receiver import X\nY = X + 1\n',
            'container_candidate_commit': (
                'from sandbox_snapshot_receiver import X\n'
                'from snapshot_git_tree import Y\n'
                'def build_candidate(raw, digest, blobs, bundle, bundle_sha256, parent_ref):\n'
                '    assert raw == b"manifest" and blobs == {"blob": b"content"}\n'
                '    assert bundle == b"parent" and parent_ref == "refs/heads/feature/test"\n'
                '    return {"mode": "build", "sum": X + Y}, b"built"\n'
                'def verify_import(raw, digest, blobs, bundle, metadata):\n'
                '    assert raw == b"manifest" and blobs == {"blob": b"content"}\n'
                '    assert bundle == b"candidate" and metadata == {"synthetic": True}\n'
                '    return {"mode": "import", "sum": X + Y}, b"imported"\n'),
        }
        encode = lambda data: base64.b64encode(data).decode()
        packet = dict(modules=modules, manifest=encode(b'manifest'), digest='synthetic',
            blobs={'blob': encode(b'content')}, parent_bundle=encode(b'parent'),
            parent_bundle_sha256='synthetic', parent_ref='refs/heads/feature/test')
        if imported:
            packet.update(verify_import=True, candidate_bundle=encode(b'candidate'),
                          candidate_metadata={'synthetic': True})
        raw = json.dumps(packet, sort_keys=True).encode()
        self.assertEqual(next(iter(json.loads(raw)['modules'])), 'container_candidate_commit')
        stdout = io.StringIO()
        missing = object()
        original = {name: sys.modules.get(name, missing) for name in modules}
        # Isolate imports from already-loaded real controller modules, and restore
        # the complete module mapping even if synthetic execution raises.
        with patch.dict(sys.modules):
            for name in modules:
                sys.modules.pop(name, None)
            with patch.object(sys, 'stdin', SimpleNamespace(buffer=io.BytesIO(raw))), \
                    patch.object(sys, 'stdout', stdout):
                exec(INNER, {'__name__': '__synthetic_packet_test__'})
        for name, previous in original.items():
            self.assertIs(sys.modules.get(name, missing), previous)
        return json.loads(stdout.getvalue())

    def test_sorted_build_packet_loads_dependencies_before_builder(self):
        result = self.invoke(False)
        self.assertEqual(result['metadata'], {'mode': 'build', 'sum': 15})
        self.assertEqual(base64.b64decode(result['bundle']), b'built')

    def test_sorted_import_packet_loads_dependencies_before_builder(self):
        result = self.invoke(True)
        self.assertEqual(result['metadata'], {'mode': 'import', 'sum': 15})
        self.assertEqual(base64.b64decode(result['bundle']), b'imported')


if __name__ == '__main__':
    unittest.main()
