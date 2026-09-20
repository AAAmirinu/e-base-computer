import base64
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from sandbox_repository import GuestRepository
from test_sandbox_repository import FakeController


class TransferController(FakeController):
    def execute(self, argv, **kwargs):
        request = json.loads(argv[5])
        if request['operation'] == 'mkdir':
            self.data = b'created'
        elif request['operation'] == 'write':
            self.data = hashlib.sha256(base64.b64decode(request['payload'])).hexdigest().encode()
        elif request['operation'] == 'assemble':
            self.data = request['sha256'].encode()
        return super().execute(argv, **kwargs)


class TransferTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.controller = TransferController()
        self.repo = GuestRepository(self.controller, '/home/agent/repo', Path(self.tmp.name))

    def test_large_binary_split_and_whole_digest(self):
        payload = bytes(range(256)) * 400
        self.repo.write_large_bytes('inputs/context.json', payload)
        requests = [json.loads(call[0][5]) for call in self.controller.calls]
        chunks = [base64.b64decode(r['payload']) for r in requests if r['operation'] == 'write']
        self.assertEqual(b''.join(chunks), payload)
        self.assertTrue(all(len(c) <= 32768 for c in chunks))
        final = requests[-1]
        self.assertEqual(final['operation'], 'assemble')
        self.assertEqual(final['size'], len(payload))
        self.assertEqual(final['sha256'], hashlib.sha256(payload).hexdigest())
        self.assertEqual(final['relative'], 'inputs/context.json')

    def test_small_payload_uses_existing_atomic_write(self):
        self.repo.write_large_bytes('empty', b'')
        self.assertEqual(len(self.controller.calls), 1)
        self.assertEqual(json.loads(self.controller.calls[0][0][5])['operation'], 'write')

    def test_invalid_transfer_has_no_side_effects(self):
        for path, data in (('../escape', b'a' * 40000), ('file', 'text'), ('file', b'x' * 16777217)):
            with self.assertRaises(ValueError):
                self.repo.write_large_bytes(path, data)
        self.assertEqual(self.controller.calls, [])

    def test_exact_upper_bound_has_512_bounded_chunks(self):
        payload = b'a' * (16 * 1024 * 1024)
        self.repo.make_directory = Mock()
        sizes = []
        self.repo.write_bytes = lambda path, data: sizes.append(len(data))
        self.repo._call = Mock(return_value=hashlib.sha256(payload).hexdigest().encode())
        self.repo.write_large_bytes('large', payload)
        self.assertEqual(sizes, [32768] * 512)


if __name__ == '__main__':
    unittest.main()
