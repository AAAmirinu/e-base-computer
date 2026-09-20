"""Trusted driver tests using an in-memory repository; no Git or VM processes."""
import hashlib
import unittest
from types import SimpleNamespace

from sandbox_metadata import configure_guest_metadata


EXCLUDE = '.git/info/exclude'


class FakeRepository:
    def __init__(self, previous=b'# existing\r\n*.cache'):
        self.guest_root = '/home/agent/workspace/machine'
        self.kinds = {'.git': 'directory', '.git/info': 'directory',
                      EXCLUDE: 'missing' if previous is None else 'regular'}
        self.files = {} if previous is None else {EXCLUDE: previous}
        self.events = []
        self.head_reads = 0
        self.change_head = False
        self.tracked = ''
        self.git_dir = self.guest_root + '/.git'
        self.bad_digest = False
        self.read_error = False
        self.mkdir_error = None
        self.stopped = False
        self.controller = SimpleNamespace(stop=self.stop)

    def stop(self):
        self.stopped = True

    def git(self, *args):
        self.events.append(('git', args))
        if args == ('rev-parse', 'HEAD'):
            self.head_reads += 1
            return ('b' if self.change_head and self.head_reads > 1 else 'a') * 40 + '\n'
        if args == ('rev-parse', '--absolute-git-dir'):
            return self.git_dir + '\n'
        if args == ('ls-files', '-z', '--', '.fleet'):
            return self.tracked
        raise AssertionError('Unexpected Git call: ' + repr(args))

    def path_kind(self, path):
        self.events.append(('kind', path))
        return self.kinds.get(path, 'missing')

    def read_bytes(self, path, *, max_bytes):
        self.events.append(('read', path, max_bytes))
        if self.read_error or len(self.files[path]) > max_bytes:
            raise RuntimeError('Bounded read failed')
        return self.files[path]

    def make_directory(self, path):
        self.events.append(('mkdir', path))
        if path == self.mkdir_error:
            raise RuntimeError('Injected directory creation failure')
        if self.kinds.get(path, 'missing') != 'missing':
            raise RuntimeError('Existing directory')
        self.kinds[path] = 'directory'

    def write_bytes(self, path, payload):
        self.events.append(('write', path, payload))
        self.files[path] = payload
        self.kinds[path] = 'regular'
        return hashlib.sha256(payload).hexdigest()

    def sha256(self, path, *, max_bytes):
        self.events.append(('sha256', path, max_bytes))
        return '0' * 64 if self.bad_digest else hashlib.sha256(self.files[path]).hexdigest()


class MetadataTests(unittest.TestCase):
    def assert_no_writes(self, repo):
        self.assertFalse(any(event[0] in ('mkdir', 'write') for event in repo.events))

    def test_existing_bytes_preserved_and_backed_up(self):
        previous = b'# binary comment\xff\r\n*.cache'
        repo = FakeRepository(previous)
        result = configure_guest_metadata(repo)
        expected = previous + b'\n/.fleet/\n'
        self.assertTrue(result['changed'])
        self.assertEqual(repo.files[EXCLUDE], expected)
        self.assertEqual(repo.files[result['backup']], previous)
        self.assertTrue(result['backup'].startswith('.fleet/metadata-config-'))
        self.assertEqual(result['before_sha256'], hashlib.sha256(previous).hexdigest())
        self.assertEqual(result['after_sha256'], hashlib.sha256(expected).hexdigest())
        self.assertGreaterEqual(repo.head_reads, 2)

    def test_missing_exclude_creates_rule_and_empty_backup(self):
        repo = FakeRepository(None)
        result = configure_guest_metadata(repo)
        self.assertTrue(result['changed'])
        self.assertEqual(repo.files[EXCLUDE], b'\n/.fleet/\n')
        self.assertEqual(repo.files[result['backup']], b'')
        self.assertFalse(any(event[0] == 'read' for event in repo.events))

    def test_exact_rule_is_idempotent(self):
        for existing in (b'/.fleet/', b'# hi\r\n*.tmp\r\n/.fleet/\r\n# trailing comment\n\n'):
            with self.subTest(existing=existing):
                repo = FakeRepository(existing)
                self.assertFalse(configure_guest_metadata(repo)['changed'])
                self.assertEqual(repo.files[EXCLUDE], existing)
                self.assert_no_writes(repo)

    def test_missing_info_directory_is_created_before_exclude(self):
        repo = FakeRepository(None)
        repo.kinds['.git/info'] = 'missing'
        result = configure_guest_metadata(repo)
        self.assertTrue(result['changed'])
        self.assertEqual(repo.kinds['.git/info'], 'directory')
        self.assertEqual(repo.files[EXCLUDE], b'\n/.fleet/\n')
        mutations = [event for event in repo.events if event[0] in ('mkdir', 'write')]
        self.assertEqual(mutations[0], ('mkdir', '.git/info'))

    def test_failed_info_creation_prevents_file_writes(self):
        repo = FakeRepository(None)
        repo.kinds['.git/info'] = 'missing'
        repo.mkdir_error = '.git/info'
        with self.assertRaisesRegex(RuntimeError, 'directory creation failure'):
            configure_guest_metadata(repo)
        self.assertFalse(any(event[0] == 'write' for event in repo.events))
        self.assertEqual(repo.files, {})
        self.assertEqual([event for event in repo.events if event[0] == 'mkdir'],
                         [('mkdir', '.git/info')])

    def test_similar_rule_does_not_count_as_exact(self):
        repo = FakeRepository(b'!/.fleet/\n# /.fleet/\n/.fleet/*')
        self.assertTrue(configure_guest_metadata(repo)['changed'])
        self.assertTrue(repo.files[EXCLUDE].endswith(b'\n/.fleet/\n'))

    def test_trailing_negation_is_overridden_without_discarding_existing_bytes(self):
        previous = b'/.fleet/\n!/.fleet/\n# retain this comment\n'
        repo = FakeRepository(previous)
        result = configure_guest_metadata(repo)
        self.assertTrue(result['changed'])
        self.assertEqual(repo.files[EXCLUDE], previous + b'\n/.fleet/\n')
        self.assertEqual(repo.files[result['backup']], previous)
        repo.events.clear()
        self.assertFalse(configure_guest_metadata(repo)['changed'])
        self.assert_no_writes(repo)

    def test_unsafe_git_directory_shapes_rejected(self):
        for path in ('.git', '.git/info'):
            for kind in ('regular', 'missing', 'symlink', 'hardlink', 'other'):
                if path == '.git/info' and kind == 'missing':
                    continue
                with self.subTest(path=path, kind=kind):
                    repo = FakeRepository()
                    repo.kinds[path] = kind
                    with self.assertRaises(Exception):
                        configure_guest_metadata(repo)
                    self.assert_no_writes(repo)

    def test_unsafe_exclude_shapes_rejected_even_with_existing_rule(self):
        for kind in ('directory', 'symlink', 'hardlink', 'other'):
            with self.subTest(kind=kind):
                repo = FakeRepository(b'/.fleet/\n')
                repo.kinds[EXCLUDE] = kind
                with self.assertRaises(Exception):
                    configure_guest_metadata(repo)
                self.assert_no_writes(repo)

    def test_external_git_directory_rejected(self):
        repo = FakeRepository()
        repo.git_dir = '/somewhere/else/.git'
        with self.assertRaises(Exception):
            configure_guest_metadata(repo)
        self.assert_no_writes(repo)

    def test_tracked_fleet_rejected_even_if_excluded(self):
        repo = FakeRepository(b'/.fleet/\n')
        repo.tracked = '.fleet/important.json\0'
        with self.assertRaises(Exception):
            configure_guest_metadata(repo)
        self.assert_no_writes(repo)

    def test_digest_mismatch_does_not_report_success(self):
        repo = FakeRepository()
        repo.bad_digest = True
        with self.assertRaises(Exception):
            configure_guest_metadata(repo)

    def test_head_change_does_not_report_success(self):
        repo = FakeRepository()
        repo.change_head = True
        with self.assertRaises(Exception):
            configure_guest_metadata(repo)

    def test_old_exclude_read_is_bounded(self):
        repo = FakeRepository(b'x' * (30 * 1024 + 1))
        with self.assertRaises(Exception):
            configure_guest_metadata(repo)
        self.assertIn(('read', EXCLUDE, 30 * 1024), repo.events)
        self.assert_no_writes(repo)

    def test_read_error_is_not_treated_as_missing(self):
        repo = FakeRepository()
        repo.read_error = True
        with self.assertRaises(Exception):
            configure_guest_metadata(repo)
        self.assert_no_writes(repo)


if __name__ == '__main__':
    unittest.main()
