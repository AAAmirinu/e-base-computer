"""Driver-only transfer tests: fake VM leases, no child processes or Git."""
from contextlib import contextmanager
import hashlib
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from sandbox_transfer import transfer_commit


COMMIT = 'a' * 40
LIMIT = 16 * 1024 * 1024


class FakeRepository:
    def __init__(self, runtime, role):
        self.runtime, self.role = runtime, role
        self.guest_root = '/home/agent/workspace/' + role
        self.controller = SimpleNamespace(sandbox_id=role + '-uuid')
        self.head = ('b' if role == 'machine' else 'c') * 40
        self.head_reads = 0
        self.change_head = False
        self.resolved_commit = COMMIT
        self.payload = b'full reachable bundle\x00\xff'
        self.digest_override = None
        self.fail_operation = None
        self.bundle_ref = None
        self.advertised_override = None

    def record(self, operation, *args):
        if self.runtime.active != self.role:
            raise AssertionError('Repository accessed outside its lease')
        self.runtime.events.append((self.role, operation, *args))
        if operation == self.fail_operation:
            raise RuntimeError('Injected ' + operation + ' failure')

    def git(self, *args):
        self.record('git', *args)
        if args == ('rev-parse', 'HEAD'):
            self.head_reads += 1
            return ('d' * 40 if self.change_head and self.head_reads > 1 else self.head) + '\n'
        if args == ('rev-parse', '--verify', COMMIT + '^{commit}'):
            return self.resolved_commit + '\n'
        if args[0] == 'update-ref':
            if len(args) != 4 or args[2:] != (COMMIT, '0' * 40):
                raise AssertionError('Transfer ref must be create-only and retained')
            self.bundle_ref = args[1]
            return ''
        if args[:2] == ('bundle', 'list-heads'):
            if self.advertised_override is not None:
                return self.advertised_override
            return COMMIT + ' ' + args[3] + '\n'
        if args[:2] in (('bundle', 'create'), ('bundle', 'verify')):
            return ''
        if args[:3] == ('fetch', '--no-tags', '--no-write-fetch-head'):
            return ''
        raise AssertionError('Unexpected Git operation: ' + repr(args))

    def make_directory(self, relative):
        self.record('mkdir', relative)

    def read_bytes(self, relative, *, max_bytes):
        self.record('read', relative, max_bytes)
        if len(self.payload) > max_bytes:
            raise RuntimeError('Bounded read overflow')
        return self.payload

    def write_large_bytes(self, relative, payload):
        self.record('write', relative, payload)
        self.payload = payload

    def sha256(self, relative, *, max_bytes):
        self.record('sha256', relative, max_bytes)
        return self.digest_override or hashlib.sha256(self.payload).hexdigest()


class FakeRuntime:
    def __init__(self):
        self.registration = {'roles': {'machine': {}, 'coordinator': {}}}
        self.events = []
        self.active = None
        self.repos = {role: FakeRepository(self, role) for role in self.registration['roles']}

    @contextmanager
    def role(self, role):
        if self.active is not None:
            raise AssertionError('Overlapping VM leases')
        self.active = role
        self.events.append(('enter', role))
        try:
            yield self.repos[role]
        finally:
            self.events.append(('exit', role))
            self.active = None


class TransferTests(unittest.TestCase):
    def setUp(self):
        self.runtime = FakeRuntime()
        self.source = self.runtime.repos['machine']
        self.target = self.runtime.repos['coordinator']
        # A regression to host Git/process execution must fail, not actually run.
        for name in ('subprocess.run', 'subprocess.Popen', 'os.system'):
            guard = patch(name, side_effect=AssertionError('Host execution forbidden'))
            guard.start()
            self.addCleanup(guard.stop)

    def transfer(self):
        return transfer_commit(self.runtime, 'machine', 'coordinator', COMMIT)

    def test_sequential_leases_retained_commit_ref_and_exact_fetch(self):
        receipt = self.transfer()
        events = self.runtime.events
        self.assertEqual([e for e in events if e[0] in ('enter', 'exit')], [
            ('enter', 'machine'), ('exit', 'machine'),
            ('enter', 'coordinator'), ('exit', 'coordinator')])
        relative = receipt['relative']
        self.assertRegex(relative, r'^\.fleet/object-transfer-[0-9a-f]{32}/objects\.bundle$')
        bundle_ref = receipt['bundle_ref']
        self.assertEqual(bundle_ref, 'refs/fleet-transfers/' + receipt['operation_id'])
        self.assertRegex(bundle_ref, r'^refs/fleet-transfers/[0-9a-f]{32}$')
        ref_event = ('machine', 'git', 'update-ref', bundle_ref, COMMIT, '0' * 40)
        create_event = ('machine', 'git', 'bundle', 'create', self.source.guest_root + '/' + relative, bundle_ref)
        self.assertIn(ref_event, events)
        self.assertIn(create_event, events)
        self.assertLess(events.index(ref_event), events.index(create_event))
        self.assertIn(('machine', 'git', 'bundle', 'list-heads', self.source.guest_root + '/' + relative, bundle_ref), events)
        self.assertEqual([e for e in events if e[1:3] == ('git', 'update-ref')], [ref_event])
        self.assertEqual(self.source.bundle_ref, bundle_ref)
        self.assertIn(('machine', 'read', relative, LIMIT), events)
        self.assertIn(('coordinator', 'write', relative, self.source.payload), events)
        digest_event = ('coordinator', 'sha256', relative, LIMIT)
        verify_event = ('coordinator', 'git', 'bundle', 'verify', self.target.guest_root + '/' + relative)
        fetch_event = ('coordinator', 'git', 'fetch', '--no-tags', '--no-write-fetch-head', self.target.guest_root + '/' + relative, bundle_ref)
        self.assertLess(events.index(digest_event), events.index(verify_event))
        self.assertLess(events.index(verify_event), events.index(fetch_event))
        for role in ('machine', 'coordinator'):
            self.assertIn((role, 'git', 'rev-parse', '--verify', COMMIT + '^{commit}'), events)
            self.assertEqual(events.count((role, 'git', 'rev-parse', 'HEAD')), 2)
        self.assertFalse(any(e[1:3] in (('git', 'merge'), ('git', 'checkout'), ('git', 'remote')) for e in events))
        self.assertEqual(receipt['bundle_sha256'], hashlib.sha256(self.source.payload).hexdigest())
        self.assertEqual(receipt['bundle_bytes'], len(self.source.payload))
        self.assertEqual(receipt['source_id'], 'machine-uuid')
        self.assertEqual(receipt['target_id'], 'coordinator-uuid')
        self.assertEqual(receipt['source_head'], self.source.head)
        self.assertEqual(receipt['target_head'], self.target.head)
        self.assertEqual(receipt['commit'], COMMIT)
        self.assertIsNone(self.runtime.active)

    def test_advertised_identity_mismatch_refuses_target_and_retains_ref(self):
        for advertised in ('', 'e' * 40 + ' {ref}\n', COMMIT + ' refs/heads/other\n',
                           COMMIT + ' {ref}\n' + COMMIT + ' {ref}\n'):
            with self.subTest(advertised=advertised):
                self.runtime = FakeRuntime()
                source = self.runtime.repos['machine']
                operation_id = '1' * 32
                bundle_ref = 'refs/fleet-transfers/' + operation_id
                source.advertised_override = advertised.format(ref=bundle_ref)
                with patch('sandbox_transfer.uuid.uuid4', return_value=SimpleNamespace(hex=operation_id)):
                    with self.assertRaises(RuntimeError):
                        self.transfer()
                self.assertNotIn(('enter', 'coordinator'), self.runtime.events)
                self.assertEqual(source.bundle_ref, bundle_ref)
                self.assertEqual([e for e in self.runtime.events if e[1:3] == ('git', 'update-ref')], [
                    ('machine', 'git', 'update-ref', bundle_ref, COMMIT, '0' * 40)])
                self.assertIsNone(self.runtime.active)

    def test_invalid_roles_and_commits_never_acquire_lease(self):
        for source, target in [('machine', 'machine'), ('missing', 'coordinator'), ('machine', 'missing')]:
            with self.subTest(source=source, target=target), self.assertRaises(ValueError):
                transfer_commit(self.runtime, source, target, COMMIT)
        for commit in (None, 42, '', 'a' * 39, 'a' * 41, 'A' * 40, 'g' * 40, '--all', 'HEAD'):
            with self.subTest(commit=commit), self.assertRaises(ValueError):
                transfer_commit(self.runtime, 'machine', 'coordinator', commit)
        self.assertEqual(self.runtime.events, [])

    def test_source_commit_mismatch_releases_and_never_enters_target(self):
        self.source.resolved_commit = 'e' * 40
        with self.assertRaisesRegex(RuntimeError, 'Source commit identity'):
            self.transfer()
        self.assertNotIn(('enter', 'coordinator'), self.runtime.events)
        self.assertIsNone(self.runtime.active)

    def test_source_head_change_or_empty_bundle_refuses_target(self):
        for mode in ('head', 'empty'):
            with self.subTest(mode=mode):
                self.runtime = FakeRuntime()
                source = self.runtime.repos['machine']
                source.change_head = mode == 'head'
                if mode == 'empty':
                    source.payload = b''
                with self.assertRaisesRegex(RuntimeError, 'Empty bundle or source HEAD'):
                    self.transfer()
                self.assertNotIn(('enter', 'coordinator'), self.runtime.events)
                self.assertIsNone(self.runtime.active)

    def test_read_overflow_releases_source(self):
        self.source.payload = b'x' * (LIMIT + 1)
        with self.assertRaisesRegex(RuntimeError, 'overflow'):
            self.transfer()
        self.assertNotIn(('enter', 'coordinator'), self.runtime.events)
        self.assertIsNone(self.runtime.active)

    def test_corrupt_transfer_releases_target_before_git_import(self):
        self.target.digest_override = '0' * 64
        with self.assertRaisesRegex(RuntimeError, 'digest mismatch'):
            self.transfer()
        self.assertFalse(any(e[:3] == ('coordinator', 'git', 'bundle') or e[:3] == ('coordinator', 'git', 'fetch') for e in self.runtime.events))
        self.assertIsNone(self.runtime.active)

    def test_target_commit_and_head_mismatches_release_target(self):
        for mode in ('commit', 'head'):
            with self.subTest(mode=mode):
                self.runtime = FakeRuntime()
                target = self.runtime.repos['coordinator']
                target.change_head = mode == 'head'
                if mode == 'commit':
                    target.resolved_commit = 'e' * 40
                with self.assertRaisesRegex(RuntimeError, 'Imported commit identity|Target HEAD changed'):
                    self.transfer()
                self.assertIsNone(self.runtime.active)
                self.assertEqual(self.runtime.events[-1], ('exit', 'coordinator'))

    def test_operation_exceptions_release_current_lease_without_retry(self):
        for role, operation in [('machine', 'git'), ('machine', 'mkdir'), ('machine', 'read'),
                                ('coordinator', 'git'), ('coordinator', 'mkdir'),
                                ('coordinator', 'write'), ('coordinator', 'sha256')]:
            with self.subTest(role=role, operation=operation):
                self.runtime = FakeRuntime()
                self.runtime.repos[role].fail_operation = operation
                with self.assertRaisesRegex(RuntimeError, 'Injected'):
                    self.transfer()
                self.assertIsNone(self.runtime.active)
                self.assertEqual(self.runtime.events[-1], ('exit', role))
                self.assertEqual(self.runtime.events.count(('enter', role)), 1)


if __name__ == '__main__':
    unittest.main()
