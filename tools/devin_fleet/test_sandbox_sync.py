"""Trusted-driver synchronization contract tests; no host Git or processes."""
from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from sandbox_sync import synchronize_fast_forward


OLD = 'a' * 40
BASE = 'b' * 40
EPOCH = '19abcd01-1234-4567-89ab-0123456789ab'
STATUS = ('status', '--porcelain=v1', '-z', '--untracked-files=all')
HEAD_REF = ('rev-parse', '--symbolic-full-name', 'HEAD')
GIT_DIR = ('rev-parse', '--absolute-git-dir')
OPERATION_MARKERS = ('index.lock', 'HEAD.lock', 'MERGE_HEAD', 'MERGE_AUTOSTASH',
                     'CHERRY_PICK_HEAD', 'REVERT_HEAD', 'rebase-merge',
                     'rebase-apply', 'sequencer', 'BISECT_START')
CLEAN_CHECK = [('path_kind', '.git'), GIT_DIR] + [
    ('path_kind', '.git/' + marker) for marker in OPERATION_MARKERS
] + [('rev-parse', 'HEAD'), STATUS, HEAD_REF]
MERGE = ('-c', 'core.hooksPath=/dev/null', '-c', 'merge.autoStash=false',
         'merge', '--ff-only', '--no-edit', '--no-autostash',
         '--no-overwrite-ignore', BASE)


class Repository:
    def __init__(self, runtime):
        self.runtime = runtime
        self.controller = SimpleNamespace(sandbox_id='target-uuid')
        self.head = OLD
        self.head_ref = 'HEAD'
        self.guest_root = '/home/agent/workspace/machine'
        self.status = ''
        self.ancestor = OLD
        self.fail_merge = False
        self.bad_merge_head = False
        self.dirty_after_merge = False
        self.path_kinds = {'.git': 'directory'}
        self.git_dir = None

    def path_kind(self, relative):
        assert self.runtime.active == 'machine', 'Repository used outside lease'
        self.runtime.events.append(('path_kind', relative))
        return self.path_kinds.get(relative, 'missing')

    def git(self, *args):
        assert self.runtime.active == 'machine', 'Repository used outside lease'
        self.runtime.events.append(args)
        if args == GIT_DIR:
            return (self.git_dir or self.guest_root + '/.git') + '\n'
        if args == ('rev-parse', 'HEAD'):
            return self.head + '\n'
        if args == HEAD_REF:
            return self.head_ref + '\n'
        if args == STATUS:
            return self.status
        if args == ('merge-base', OLD, BASE):
            return self.ancestor + '\n'
        if args == MERGE:
            self.runtime.phase_at_merge = self.runtime.receipt()['phase']
            if self.fail_merge:
                raise RuntimeError('merge injected failure')
            self.head = 'c' * 40 if self.bad_merge_head else BASE
            if self.dirty_after_merge:
                self.status = '?? changed\x00'
            return ''
        raise AssertionError('Unexpected Git call: ' + repr(args))


class Runtime:
    def __init__(self, journal):
        self.registration = {'backend': 'sandbox', 'migration_epoch': EPOCH,
                             'roles': {'machine': {'id': 'target-uuid'},
                                       'coordinator': {'id': 'source-uuid'}}}
        self.active = None
        self.events = []
        self.leases = []
        self.journal = journal
        self.repo = Repository(self)
        self.phase_at_merge = None
        self.fail_exit_number = None

    def receipt(self):
        return json.loads((self.journal / 'receipt.json').read_text(encoding='utf-8'))

    @contextmanager
    def role(self, role):
        assert self.active is None, 'Overlapping leases'
        self.active = role
        self.leases.append(role)
        try:
            yield self.repo
        finally:
            self.active = None
            if self.fail_exit_number == len(self.leases):
                raise RuntimeError('VM stop injected failure')


class SynchronizeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.journal = Path(tmp.name) / 'fresh-journal'
        self.runtime = Runtime(self.journal)
        self.phase_at_transfer = None
        for name in ('subprocess.run', 'subprocess.Popen', 'os.system'):
            guard = patch(name, side_effect=AssertionError('Host execution forbidden'))
            guard.start()
            self.addCleanup(guard.stop)
        self.transfer_patch = patch('sandbox_sync.transfer_commit', side_effect=self.transfer)
        self.mock_transfer = self.transfer_patch.start()
        self.addCleanup(self.transfer_patch.stop)

    def transfer(self, runtime, source, target, baseline):
        self.assertIs(runtime, self.runtime)
        self.assertIsNone(runtime.active)
        self.assertEqual((source, target, baseline), ('coordinator', 'machine', BASE))
        self.phase_at_transfer = runtime.receipt()['phase']
        return {'commit': baseline, 'bundle_sha256': 'd' * 64}

    def sync(self, **overrides):
        args = dict(runtime=self.runtime, source_role='coordinator', target_role='machine',
                    baseline=BASE, expected_head=OLD, journal_directory=self.journal)
        args.update(overrides)
        return synchronize_fast_forward(**args)

    def test_success_rechecks_before_exact_fast_forward_and_durable_complete(self):
        receipt = self.sync()
        self.assertEqual(self.phase_at_transfer, 'prepared')
        self.assertEqual(self.runtime.phase_at_merge, 'applying')
        self.assertEqual(self.runtime.receipt()['phase'], 'complete')
        self.assertEqual(receipt, self.runtime.receipt())
        self.assertEqual(receipt['schema'], 2)
        self.assertEqual(receipt['migration_epoch'], EPOCH)
        self.assertRegex(receipt['operation_id'], r'\A[0-9a-f]{32}\Z')
        self.assertEqual(receipt['head_ref'], 'HEAD')
        self.assertEqual(receipt['guest_root'], '/home/agent/workspace/machine')
        self.assertEqual(self.runtime.events,
                         CLEAN_CHECK + CLEAN_CHECK +
                         [('merge-base', OLD, BASE), MERGE] + CLEAN_CHECK)
        self.assertEqual(self.runtime.leases, ['machine', 'machine'])
        self.assertIsNone(self.runtime.active)

    def test_noop_still_checks_clean_expected_head_without_transfer(self):
        self.sync(baseline=OLD)
        self.mock_transfer.assert_not_called()
        self.assertEqual(self.runtime.events, CLEAN_CHECK)
        self.assertEqual(self.runtime.receipt()['phase'], 'complete')
        self.assertEqual(self.runtime.receipt()['schema'], 2)
        self.assertEqual(self.runtime.receipt()['migration_epoch'], EPOCH)
        self.assertRegex(self.runtime.receipt()['operation_id'], r'\A[0-9a-f]{32}\Z')

    def test_missing_epoch_or_backend_refused_before_journal_or_lease(self):
        for key in ('migration_epoch', 'backend'):
            with self.subTest(key=key):
                original = self.runtime.registration.pop(key)
                try:
                    with self.assertRaises(ValueError):
                        self.sync()
                finally:
                    self.runtime.registration[key] = original
                self.assertEqual(self.runtime.leases, [])
                self.assertFalse(self.journal.exists())
                self.mock_transfer.assert_not_called()

    def test_noncanonical_or_invalid_epoch_refused_before_journal_or_lease(self):
        for value in (None, True, 42, '', 'legacy', EPOCH.upper(),
                      EPOCH.replace('-', ''), '{' + EPOCH + '}',
                      'urn:uuid:' + EPOCH, EPOCH + ' ', ' ' + EPOCH):
            with self.subTest(epoch=value):
                self.runtime.registration['migration_epoch'] = value
                with self.assertRaises(ValueError):
                    self.sync()
                self.assertEqual(self.runtime.leases, [])
                self.assertFalse(self.journal.exists())
                self.mock_transfer.assert_not_called()

    def test_non_sandbox_backend_refused_before_journal_or_lease(self):
        for value in (None, True, 42, '', 'local', 'Sandbox', 'sandbox '):
            with self.subTest(backend=value):
                self.runtime.registration['backend'] = value
                with self.assertRaises(ValueError):
                    self.sync()
                self.assertEqual(self.runtime.leases, [])
                self.assertFalse(self.journal.exists())
                self.mock_transfer.assert_not_called()

    def test_invalid_roles_and_hashes_fail_before_any_lease(self):
        bad = [{'target_role': 'coordinator'}, {'source_role': 'missing'}, {'target_role': 'missing'}]
        for key in ('baseline', 'expected_head'):
            bad.extend({key: value} for value in (None, 42, '', 'HEAD', 'A' * 40, 'g' * 40, 'a' * 39))
        for override in bad:
            with self.subTest(override=override), self.assertRaises(ValueError):
                self.sync(**override)
        self.assertEqual(self.runtime.leases, [])
        self.assertFalse(self.journal.exists())

    def test_relative_journal_refused_without_lease(self):
        with self.assertRaises(ValueError):
            self.sync(journal_directory=Path('relative-journal'))
        self.assertEqual(self.runtime.leases, [])

    def test_existing_journal_not_overwritten(self):
        self.journal.mkdir()
        sentinel = self.journal / 'receipt.json'
        sentinel.write_bytes(b'previous durable receipt')
        with self.assertRaises((ValueError, FileExistsError)):
            self.sync()
        self.assertEqual(sentinel.read_bytes(), b'previous durable receipt')
        self.assertEqual(self.runtime.leases, [])

    def test_missing_journal_parent_not_created(self):
        missing = self.journal / 'missing-parent' / 'journal'
        with self.assertRaises(FileNotFoundError):
            self.sync(journal_directory=missing)
        self.assertFalse(self.journal.exists())
        self.assertEqual(self.runtime.leases, [])

    def test_parent_fsync_failure_refused_before_receipt_or_leases(self):
        with patch('sandbox_sync._sync_directory', side_effect=OSError('fsync injected failure')) as sync:
            with self.assertRaisesRegex(OSError, 'fsync injected'):
                self.sync()
        sync.assert_called_once_with(self.journal.parent)
        self.assertTrue(self.journal.is_dir())
        self.assertFalse((self.journal / 'receipt.json').exists())
        self.assertEqual(self.runtime.leases, [])
        self.mock_transfer.assert_not_called()

    def test_dirty_target_refused_before_transfer(self):
        self.runtime.repo.status = '?? important\x00'
        with self.assertRaises(RuntimeError):
            self.sync()
        self.mock_transfer.assert_not_called()
        self.assertNotIn(MERGE, self.runtime.events)
        self.assertIsNone(self.runtime.active)

    def test_each_operation_marker_refused_before_status_or_transfer(self):
        for marker in OPERATION_MARKERS:
            for kind in ('regular', 'directory', 'symlink', 'hardlink', 'other'):
                with self.subTest(marker=marker, kind=kind):
                    self.runtime.repo.path_kinds = {'.git': 'directory', '.git/' + marker: kind}
                    self.runtime.events.clear()
                    journal = self.journal.parent / (marker + '-' + kind)
                    with self.assertRaises(RuntimeError):
                        self.sync(journal_directory=journal)
                    self.mock_transfer.assert_not_called()
                    self.assertNotIn(STATUS, self.runtime.events)
                    self.assertNotIn(MERGE, self.runtime.events)
                    self.assertIsNone(self.runtime.active)

    def test_non_directory_git_metadata_refused_before_git_or_transfer(self):
        for kind in ('regular', 'symlink', 'hardlink', 'missing', 'other'):
            with self.subTest(kind=kind):
                self.runtime.repo.path_kinds['.git'] = kind
                self.runtime.events.clear()
                with self.assertRaises(RuntimeError):
                    self.sync(journal_directory=self.journal.parent / ('git-' + kind))
                self.assertEqual(self.runtime.events, [('path_kind', '.git')])
                self.mock_transfer.assert_not_called()
                self.assertIsNone(self.runtime.active)

    def test_relocated_git_directory_refused_before_status_or_transfer(self):
        self.runtime.repo.git_dir = '/home/agent/elsewhere/.git'
        with self.assertRaises(RuntimeError):
            self.sync()
        self.assertEqual(self.runtime.events, [('path_kind', '.git'), GIT_DIR])
        self.mock_transfer.assert_not_called()
        self.assertIsNone(self.runtime.active)

    def test_operation_started_during_transfer_refused_before_merge(self):
        def change(*args):
            result = self.transfer(*args)
            self.runtime.repo.path_kinds['.git/MERGE_HEAD'] = 'regular'
            return result
        self.mock_transfer.side_effect = change
        with self.assertRaises(RuntimeError):
            self.sync()
        self.assertEqual(self.runtime.receipt()['phase'], 'transferred')
        self.assertEqual(self.runtime.events.count(STATUS), 1)
        self.assertNotIn(MERGE, self.runtime.events)
        self.assertIsNone(self.runtime.active)

    def test_post_merge_operation_marker_never_reports_complete(self):
        original_git = self.runtime.repo.git
        def change(*args):
            result = original_git(*args)
            if args == MERGE:
                self.runtime.repo.path_kinds['.git/MERGE_AUTOSTASH'] = 'regular'
            return result
        with patch.object(self.runtime.repo, 'git', side_effect=change):
            with self.assertRaises(RuntimeError):
                self.sync()
        self.assertEqual(self.runtime.receipt()['phase'], 'applying')
        self.assertEqual(self.runtime.events.count(MERGE), 1)
        self.assertIsNone(self.runtime.active)

    def test_stale_head_refused_before_transfer(self):
        self.runtime.repo.head = 'c' * 40
        with self.assertRaises(RuntimeError):
            self.sync()
        self.mock_transfer.assert_not_called()
        self.assertNotIn(MERGE, self.runtime.events)

    def test_transfer_failure_retains_prepared_receipt(self):
        self.mock_transfer.side_effect = RuntimeError('transfer injected failure')
        with self.assertRaisesRegex(RuntimeError, 'transfer injected'):
            self.sync()
        self.assertEqual(self.runtime.receipt()['phase'], 'prepared')
        self.assertNotIn(MERGE, self.runtime.events)

    def test_target_changed_during_transfer_refused_with_transferred_receipt(self):
        def change(*args):
            result = self.transfer(*args)
            self.runtime.repo.head = 'c' * 40
            return result
        self.mock_transfer.side_effect = change
        with self.assertRaises(RuntimeError):
            self.sync()
        self.assertEqual(self.runtime.receipt()['phase'], 'transferred')
        self.assertNotIn(MERGE, self.runtime.events)

    def test_target_dirtied_during_transfer_refused(self):
        def change(*args):
            result = self.transfer(*args)
            self.runtime.repo.status = ' M changed\x00'
            return result
        self.mock_transfer.side_effect = change
        with self.assertRaises(RuntimeError):
            self.sync()
        self.assertEqual(self.runtime.receipt()['phase'], 'transferred')
        self.assertNotIn(MERGE, self.runtime.events)

    def test_same_commit_branch_switch_during_transfer_refused(self):
        self.runtime.repo.head_ref = 'refs/heads/original'
        def change(*args):
            result = self.transfer(*args)
            self.runtime.repo.head_ref = 'refs/heads/other'
            return result
        self.mock_transfer.side_effect = change
        with self.assertRaises(RuntimeError):
            self.sync()
        self.assertEqual(self.runtime.repo.head, OLD)
        self.assertEqual(self.runtime.receipt()['head_ref'], 'refs/heads/original')
        self.assertEqual(self.runtime.receipt()['phase'], 'transferred')
        self.assertNotIn(MERGE, self.runtime.events)
        self.assertIsNone(self.runtime.active)

    def test_guest_root_changed_during_transfer_refused(self):
        def change(*args):
            result = self.transfer(*args)
            self.runtime.repo.guest_root = '/home/agent/workspace/other'
            return result
        self.mock_transfer.side_effect = change
        with self.assertRaises(RuntimeError):
            self.sync()
        self.assertEqual(self.runtime.repo.head, OLD)
        self.assertEqual(self.runtime.receipt()['guest_root'], '/home/agent/workspace/machine')
        self.assertEqual(self.runtime.receipt()['phase'], 'transferred')
        self.assertNotIn(MERGE, self.runtime.events)
        self.assertIsNone(self.runtime.active)

    def test_divergence_refused_without_merge(self):
        self.runtime.repo.ancestor = 'c' * 40
        with self.assertRaises(RuntimeError):
            self.sync()
        self.assertEqual(self.runtime.receipt()['phase'], 'transferred')
        self.assertNotIn(MERGE, self.runtime.events)

    def test_merge_failure_keeps_applying_phase_no_retry(self):
        self.runtime.repo.fail_merge = True
        with self.assertRaisesRegex(RuntimeError, 'merge injected'):
            self.sync()
        self.assertEqual(self.runtime.receipt()['phase'], 'applying')
        self.assertEqual(self.runtime.events.count(MERGE), 1)
        self.assertIsNone(self.runtime.active)

    def test_wrong_post_merge_head_not_reported_complete(self):
        self.runtime.repo.bad_merge_head = True
        with self.assertRaises(RuntimeError):
            self.sync()
        self.assertEqual(self.runtime.receipt()['phase'], 'applying')

    def test_dirty_post_merge_not_reported_complete(self):
        self.runtime.repo.dirty_after_merge = True
        with self.assertRaises(RuntimeError):
            self.sync()
        self.assertEqual(self.runtime.receipt()['phase'], 'applying')

    def test_post_merge_branch_switch_not_reported_complete(self):
        original_git = self.runtime.repo.git
        def change(*args):
            result = original_git(*args)
            if args == MERGE:
                self.runtime.repo.head_ref = 'refs/heads/unexpected'
            return result
        with patch.object(self.runtime.repo, 'git', side_effect=change):
            with self.assertRaises(RuntimeError):
                self.sync()
        self.assertEqual(self.runtime.receipt()['phase'], 'applying')
        self.assertEqual(self.runtime.events.count(MERGE), 1)
        self.assertIsNone(self.runtime.active)

    def test_post_merge_guest_root_change_not_reported_complete(self):
        original_git = self.runtime.repo.git
        def change(*args):
            result = original_git(*args)
            if args == MERGE:
                self.runtime.repo.guest_root = '/home/agent/workspace/unexpected'
            return result
        with patch.object(self.runtime.repo, 'git', side_effect=change):
            with self.assertRaises(RuntimeError):
                self.sync()
        self.assertEqual(self.runtime.receipt()['phase'], 'applying')
        self.assertEqual(self.runtime.events.count(MERGE), 1)
        self.assertIsNone(self.runtime.active)

    def test_vm_stop_failure_after_merge_never_reports_complete(self):
        self.runtime.fail_exit_number = 2
        with self.assertRaisesRegex(RuntimeError, 'VM stop injected'):
            self.sync()
        self.assertEqual(self.runtime.repo.head, BASE)
        self.assertEqual(self.runtime.receipt()['phase'], 'applying')

    def test_vm_stop_failure_during_noop_never_reports_complete(self):
        self.runtime.fail_exit_number = 1
        with self.assertRaisesRegex(RuntimeError, 'VM stop injected'):
            self.sync(baseline=OLD)
        self.assertEqual(self.runtime.receipt()['phase'], 'prepared')
        self.mock_transfer.assert_not_called()


if __name__ == '__main__':
    unittest.main()
