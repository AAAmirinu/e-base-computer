"""Protocol/routing tests. No VM, model, git, or guest code is run on the host."""
import base64
import hashlib
import json
from pathlib import Path
import tempfile
import types
import unittest

from sandbox_control import SandboxFenced
from sandbox_repository import GuestRepository, GuestRepositoryError, _GUEST_CODE


class FakeController:
    def __init__(self):
        self.calls = []
        self.data = b'hello\x00world'
        self.mutate = lambda marker, line: b'starting sandbox\n' + line + b'\n'
        self.returncode = 0
        self.failure = None
        self.stops = 0

    def stop(self):
        self.stops += 1

    def execute(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if self.failure:
            raise self.failure
        marker = argv[4].encode('ascii')
        line = marker + json.dumps(dict(ok=True, data=base64.b64encode(self.data).decode(), error='')).encode()
        path = kwargs['log_path']
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(self.mutate(marker, line))
        return types.SimpleNamespace(returncode=self.returncode)


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.controller = FakeController()
        self.repo = GuestRepository(self.controller, '/home/agent/repo', Path(self.temp.name))

    def test_read_routes_only_fixed_isolated_python(self):
        self.assertEqual(self.repo.read_bytes('src/a.py', 100), self.controller.data)
        argv, options = self.controller.calls[0]
        self.assertEqual(argv[:4], ['python3', '-I', '-c', _GUEST_CODE])
        self.assertEqual(options['cwd'], '/')
        self.assertEqual(json.loads(argv[5]), dict(operation='read', root='/home/agent/repo', limit=100, relative='src/a.py'))
        self.assertLess(options['max_log_bytes'], 66000)

    def test_git_argv_is_data_not_shell_code(self):
        self.controller.data = b'abc\n'
        self.assertEqual(self.repo.git('show', 'x; echo BAD'), 'abc\n')
        self.assertEqual(json.loads(self.controller.calls[0][0][5])['args'], ['show', 'x; echo BAD'])

    def test_restrict_git_routes_model_reads_to_separate_guest_operation(self):
        self.controller.data = b'abc\n'
        self.repo.restrict_git_to_model_reads()
        self.repo.git('rev-parse', 'HEAD')
        request = json.loads(self.controller.calls[0][0][5])
        self.assertEqual(request['operation'], 'git_read')
        self.assertEqual(request['args'], ['rev-parse', 'HEAD'])

    def test_bound_fleet_stop_reaches_result_retrieval(self):
        stop = Path(self.temp.name) / 'FLEET_STOP'
        repo = GuestRepository(self.controller, '/home/agent/repo', Path(self.temp.name), external_stop=stop)
        repo.read_bytes('export.json')
        self.assertEqual(self.controller.calls[0][1]['external_stop'], stop)

    def test_write_is_bounded_data_with_digest_ack(self):
        payload = b'nonsecret\x00\xff'
        self.controller.data = hashlib.sha256(payload).hexdigest().encode('ascii')
        self.repo.write_bytes('context.json', payload)
        request = json.loads(self.controller.calls[0][0][5])
        self.assertEqual(request['operation'], 'write')
        self.assertEqual(base64.b64decode(request['payload']), payload)
        self.assertEqual(request['limit'], 64)

    def test_write_rejects_invalid_input_before_dispatch(self):
        for path, payload in (('../x', b'x'), ('x', 'text'), ('x', b'x' * 32769)):
            with self.assertRaises(ValueError):
                self.repo.write_bytes(path, payload)
        self.assertEqual(self.controller.calls, [])

    def test_bad_write_ack_stops_sandbox(self):
        self.controller.data = b'0' * 64
        with self.assertRaises(GuestRepositoryError):
            self.repo.write_bytes('file', b'x')
        self.assertEqual(self.controller.stops, 1)

    def test_unique_logs_and_fingerprint(self):
        expected = hashlib.sha256(self.controller.data).hexdigest()
        self.assertEqual(self.repo.sha256('file'), expected)
        self.repo.read_bytes('file')
        self.assertNotEqual(self.controller.calls[0][1]['log_path'], self.controller.calls[1][1]['log_path'])

    def test_reject_invalid_paths_before_controller(self):
        for path in ('', '/etc/passwd', '../a', 'a/../b', './a', 'a//b', 'a/', 'a\\b', 'a\x00b'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.repo.read_bytes(path)
        self.assertEqual(self.controller.calls, [])

    def test_reject_invalid_roots_and_configuration(self):
        for root in ('/', 'repo', '//home/a', '/home/../a', '/home/./a', '/home/a/', '/home\\a'):
            with self.subTest(root=root), self.assertRaises(ValueError):
                GuestRepository(self.controller, root, Path(self.temp.name))
        for limit in (0, -1, True, 1.2, 16777217):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                self.repo.read_bytes('file', limit)
        for timeout in (0, True, float('inf'), float('nan')):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                GuestRepository(self.controller, '/home/repo', Path(self.temp.name), timeout=timeout)

    def test_fence_propagates_without_retry(self):
        self.controller.failure = SandboxFenced('stopped')
        with self.assertRaises(SandboxFenced):
            self.repo.read_bytes('file')
        self.assertEqual(len(self.controller.calls), 1)
        self.assertEqual(self.controller.stops, 1)

    def test_transport_failure_is_not_success_envelope(self):
        self.controller.returncode = 1
        with self.assertRaises(GuestRepositoryError):
            self.repo.read_bytes('file')
        self.assertEqual(self.controller.stops, 1)

    def test_reject_missing_duplicate_or_oversize_envelopes(self):
        mutations = [lambda marker, line: b'no result',
                     lambda marker, line: line + b'\n' + line,
                     lambda marker, line: b'x' * 70000]
        for mutate in mutations:
            self.controller.mutate = mutate
            with self.subTest(mutate=mutate), self.assertRaises(GuestRepositoryError):
                self.repo.read_bytes('file', 100)

    def test_reject_hostile_json_payloads(self):
        for body in (b'[]', b'null', b'{}', b'{"ok":true,"ok":false,"data":"","error":""}',
                     b'{"ok":1,"data":"","error":""}',
                     b'{"ok":true,"data":"@!","error":""}',
                     b'{"ok":true,"data":"","error":"bad"}',
                     b'{"ok":true,"data":"","error":"","extra":1}',
                     b'{"ok":false,"data":"","error":"FileNotFoundError"}',
                     b'[' * 2000):
            self.controller.mutate = lambda marker, line, body=body: marker + body
            with self.subTest(body=body[:50]), self.assertRaises(GuestRepositoryError):
                self.repo.read_bytes('file')

    def test_payload_limit_and_non_utf8_git(self):
        with self.assertRaises(GuestRepositoryError):
            self.repo.read_bytes('file', 1)
        self.controller.data = b'\xff'
        with self.assertRaises(GuestRepositoryError):
            self.repo.git('status')

    def test_guest_code_compiles_but_is_never_executed_here(self):
        compile(_GUEST_CODE, '<guest-only>', 'exec')

    def test_snapshot_read_preserves_binary_and_executable_mode(self):
        payload = b'hello\x00\xff'
        self.controller.data = json.dumps({'mode': '100755', 'data': base64.b64encode(payload).decode()}).encode()
        self.assertEqual(self.repo.snapshot_file('script', 100), {'mode': '100755', 'data': payload})
        request = json.loads(self.controller.calls[-1][0][5])
        self.assertEqual(request['operation'], 'snapshot_read')
        self.assertEqual(request['file_limit'], 100)

    def test_snapshot_read_rejects_corrupt_response_and_bounds(self):
        for raw in (b'{}', b'{"mode":"120000","data":""}',
                    b'{"mode":"100644","data":"@"}',
                    b'{"mode":"100644","mode":"100755","data":""}',
                    b'{"mode":"100644","data":"YWJj"}'):
            self.controller.data = raw
            with self.subTest(raw=raw), self.assertRaises(GuestRepositoryError):
                self.repo.snapshot_file('file', 1)
        before = len(self.controller.calls)
        for limit in (True, 0, -1, 1048577):
            with self.assertRaises(ValueError):
                self.repo.snapshot_file('file', limit)
        self.assertEqual(len(self.controller.calls), before)


if __name__ == '__main__':
    unittest.main()
