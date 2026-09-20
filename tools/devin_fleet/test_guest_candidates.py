"""Controller-only candidate collection tests; no guest or host processes."""
from contextlib import contextmanager
import hashlib
from types import SimpleNamespace
import unittest

import fleet


BASE = 'a' * 40
FIRST = 'b' * 40
SECOND = 'c' * 40
THIRD = 'd' * 40


class FakeRepository:
    def __init__(self, role):
        self.controller = SimpleNamespace(sandbox_id='identity-' + role)
        self.calls = []
        self.identities = {}
        self.ancestry_error = None
        self.description = 'candidate summary  \n'
        self.diff = 'diff --git a/file b/file\n+日本語 trailing  \n\n'

    def git(self, *args):
        self.calls.append(args)
        if args[0] == 'rev-parse':
            value = args[-1].removesuffix('^{commit}')
            return self.identities.get(value, value) + '\n'
        if args[0] == 'merge-base':
            if self.ancestry_error:
                raise self.ancestry_error
            return ''
        if args[0] == 'log':
            return self.description
        if args[0] == 'diff':
            return self.diff
        raise AssertionError('Unexpected Git request: ' + repr(args))


class FakeRuntime:
    def __init__(self):
        self.registration = {'roles': dict.fromkeys(('coordinator', 'machine', 'kernel'))}
        self.repositories = {role: FakeRepository(role) for role in self.registration['roles']}
        self.events = []
        self.active = None

    @contextmanager
    def role(self, role):
        if self.active is not None:
            raise AssertionError('Overlapping role leases')
        self.active = role
        self.events.append(('enter', role))
        try:
            yield self.repositories[role]
        finally:
            self.events.append(('exit', role))
            self.active = None


def candidate(role='machine', base=BASE, status='pending'):
    return {'role': role, 'base': base, 'status': status}


class CandidateCollectionTests(unittest.TestCase):
    def setUp(self):
        self.runtime = FakeRuntime()
        self.state = {'candidates': {FIRST: candidate()}}

    def collect(self, **kwargs):
        return fleet.collect_guest_candidate_patches(self.runtime, self.state, **kwargs)

    def test_groups_each_owner_once_with_sequential_leases(self):
        self.state['candidates'] = {SECOND: candidate(), THIRD: candidate('kernel'), FIRST: candidate()}
        patches, evidence = self.collect()
        self.assertEqual(set(patches), {FIRST, SECOND, THIRD})
        self.assertEqual(set(evidence), set(patches))
        self.assertEqual(self.runtime.events, [('enter', 'kernel'), ('exit', 'kernel'),
                                              ('enter', 'machine'), ('exit', 'machine')])
        logs = [call for call in self.runtime.repositories['machine'].calls if call[0] == 'log']
        self.assertEqual(logs, [('log', '--oneline', BASE + '..' + FIRST),
                                ('log', '--oneline', BASE + '..' + SECOND)])

    def test_exact_identity_ancestry_and_binary_diff_sequence(self):
        self.collect()
        self.assertEqual(self.runtime.repositories['machine'].calls, [
            ('rev-parse', '--verify', FIRST + '^{commit}'),
            ('rev-parse', '--verify', BASE + '^{commit}'),
            ('merge-base', '--is-ancestor', BASE, FIRST),
            ('log', '--oneline', BASE + '..' + FIRST),
            ('diff', '--no-ext-diff', '--no-textconv', '--binary', '--full-index', BASE, FIRST),
        ])

    def test_whitespace_utf8_size_and_evidence_hash_preserved(self):
        repo = self.runtime.repositories['machine']
        expected = repo.description + '\n' + repo.diff
        patches, evidence = self.collect(max_bytes=len(expected.encode('utf-8')))
        self.assertEqual(patches[FIRST], expected)
        self.assertTrue(patches[FIRST].endswith('  \n\n'))
        self.assertEqual(evidence[FIRST], {'role': 'machine', 'base': BASE,
            'bytes': len(expected.encode('utf-8')),
            'sha256': hashlib.sha256(expected.encode('utf-8')).hexdigest(),
            'sandbox_id': repo.controller.sandbox_id})

    def test_non_pending_entries_do_not_lease_or_validate(self):
        self.state['candidates'] = {'invalid': {'status': 'integrated'}}
        self.assertEqual(self.collect(), ({}, {}))
        self.assertEqual(self.runtime.events, [])

    def test_invalid_owner_rejected_before_any_lease(self):
        for role in ('unknown', 'coordinator'):
            with self.subTest(role=role):
                self.state['candidates'] = {FIRST: candidate(), SECOND: candidate(role)}
                with self.assertRaises(ValueError):
                    self.collect()
                self.assertEqual(self.runtime.events, [])

    def test_invalid_commit_and_base_rejected_before_any_lease(self):
        for invalid in ('a' * 39, 'a' * 41, 'A' * 40, 'g' * 40, '--help', 42, None):
            for field in ('commit', 'base'):
                with self.subTest(invalid=invalid, field=field):
                    key = invalid if field == 'commit' else SECOND
                    base = invalid if field == 'base' else BASE
                    self.state['candidates'] = {FIRST: candidate(), key: candidate(base=base)}
                    with self.assertRaises(ValueError):
                        self.collect()
                    self.assertEqual(self.runtime.events, [])

    def test_budget_validation_before_any_lease(self):
        for invalid in (True, False, 0, -1, 16 * 1024 * 1024 + 1, 1.0, '100', None):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.collect(max_bytes=invalid)
        self.assertEqual(self.runtime.events, [])

    def test_identity_mismatch_refuses_diff_and_releases_lease(self):
        for value in (FIRST, BASE):
            with self.subTest(value=value):
                self.runtime = FakeRuntime()
                repo = self.runtime.repositories['machine']
                repo.identities[value] = THIRD
                with self.assertRaisesRegex(RuntimeError, 'identity mismatch'):
                    self.collect()
                self.assertFalse(any(call[0] in ('merge-base', 'log', 'diff') for call in repo.calls))
                self.assertEqual(self.runtime.events, [('enter', 'machine'), ('exit', 'machine')])

    def test_non_ancestor_refuses_diff_and_releases_lease(self):
        repo = self.runtime.repositories['machine']
        repo.ancestry_error = RuntimeError('not an ancestor')
        with self.assertRaisesRegex(RuntimeError, 'not an ancestor'):
            self.collect()
        self.assertFalse(any(call[0] in ('log', 'diff') for call in repo.calls))
        self.assertIsNone(self.runtime.active)

    def test_oversize_single_patch_fails_without_truncation(self):
        repo = self.runtime.repositories['machine']
        original = repo.diff
        size = len((repo.description + '\n' + original).encode('utf-8'))
        with self.assertRaisesRegex(RuntimeError, 'no truncation'):
            self.collect(max_bytes=size - 1)
        self.assertEqual(repo.diff, original)
        self.assertIsNone(self.runtime.active)

    def test_budget_is_cumulative_across_owners(self):
        self.state['candidates'][SECOND] = candidate('kernel')
        repo = self.runtime.repositories['machine']
        size = len((repo.description + '\n' + repo.diff).encode('utf-8'))
        with self.assertRaisesRegex(RuntimeError, 'no truncation'):
            self.collect(max_bytes=2 * size - 1)
        self.assertEqual(self.runtime.events, [('enter', 'kernel'), ('exit', 'kernel'),
                                              ('enter', 'machine'), ('exit', 'machine')])


if __name__ == '__main__':
    unittest.main()
