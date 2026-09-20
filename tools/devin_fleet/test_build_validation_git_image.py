"""Pure rule tests and mocked build lifecycle; never use Docker or a VM."""
import copy
from contextlib import ExitStack
import io
import json
import os
import hashlib
import tarfile
from pathlib import Path
import unittest
from unittest.mock import mock_open, patch

if os.name == 'posix':
    import build_validation_git_image as build
else:
    build = None


def rule(identity, decision='allow', resources=None, editable=True):
    return dict(id=identity, policy_id='p', editable=editable, resource_type='network',
                decision=decision, status='active', scope='sandbox:e-base-validation',
                applies_to='sandbox:e-base-validation',
                resources=resources if resources is not None else ['deb.debian.org:443'])


@unittest.skipUnless(build is not None, 'Dedicated Linux build module')
class RuleOwnershipTests(unittest.TestCase):
    def test_build_context_contains_only_two_fixed_inputs(self):
        root = Path(__file__).resolve().parent
        raw, hashes = build.build_context(root)
        self.assertEqual(build.build_context(root), (raw, hashes))
        with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
            self.assertEqual(archive.getnames(), ['Dockerfile', 'install_validation_git.py'])
            for member in archive.getmembers():
                self.assertTrue(member.isfile())
                self.assertEqual(member.mode, 0o644)
                self.assertEqual(hashes[member.name], hashlib.sha256(archive.extractfile(member).read()).hexdigest())
        compile('CONTEXT=""\n' + build.BUILD, '<guest-build>', 'exec')

    def test_duplicate_original_id_rejected(self):
        with self.assertRaises(RuntimeError):
            build.new_allow_ids([rule('old'), rule('old')], [rule('old')])

    def test_only_new_exact_scoped_allow_ids_returned(self):
        old = [rule('deny', 'deny', ['**']), rule('kit', editable=False)]
        self.assertEqual(build.new_allow_ids(old, old + [rule('new')]), ['new'])
        self.assertEqual(build.new_allow_ids(old, old), [])

    def test_existing_editable_rules_cannot_change_or_disappear(self):
        before = [rule('deny', 'deny', ['**'])]
        for after in ([], [rule('deny')]):
            with self.subTest(after=after), self.assertRaises(RuntimeError):
                build.new_allow_ids(before, after)

    def test_duplicate_current_id_rejected(self):
        with self.assertRaises(RuntimeError):
            build.new_allow_ids([], [rule('new'), rule('new')])

    def test_kit_id_churn_allowed_but_content_change_rejected(self):
        before = [rule('old', editable=False)]
        self.assertEqual(build.new_allow_ids(before, [rule('new', editable=False)]), [])
        with self.assertRaises(RuntimeError):
            build.new_allow_ids(before, [rule('new', resources=['other:443'], editable=False)])

    def test_unexpected_new_rule_rejected(self):
        for updates in ({'resources': ['deb.debian.org:80']}, {'resources': ['**']},
                        {'resources': []}, {'decision': 'deny'}, {'status': 'inactive'},
                        {'scope': 'global'}, {'applies_to': 'sandbox:e-base-machine'},
                        {'resource_type': 'filesystem'}):
            with self.subTest(updates=updates):
                row = rule('new')
                row.update(updates)
                with self.assertRaises(RuntimeError):
                    build.new_allow_ids([], [row])


@unittest.skipUnless(build is not None, 'Dedicated Linux build module')
class BuildFailureCleanupTests(unittest.TestCase):
    def scenario(self, fail_exec=True, fail_restore=False):
        rows = [rule('original-deny', 'deny', ['**'])]
        calls, receipts = [], []
        def run(*args, **kwargs):
            calls.append(args)
            if args[:3] == ('policy', 'allow', 'network'):
                rows.append(rule('owned-allow'))
            elif args[:3] == ('policy', 'deny', 'network'):
                if fail_restore:
                    raise RuntimeError('restore failed')
                rows.append(rule('restored-deny', 'deny', ['**']))
            elif args[:3] == ('policy', 'rm', 'network'):
                rows[:] = [row for row in rows if row['id'] != args[-1]]
            elif args[0] == 'exec':
                if fail_exec:
                    raise RuntimeError('synthetic build failure')
                return json.dumps(dict(built=True, image_id='sha256:' + 'a' * 64))
            return ''
        def allowed(host):
            if any(row['decision'] == 'deny' and row['resources'] == ['**'] for row in rows):
                return False
            return host == 'deb.debian.org:443'
        with ExitStack() as stack:
            for name in ('NAME', 'UUID', 'HOSTS'):
                stack.enter_context(patch.object(build.policy, name, getattr(build.policy, name)))
            stack.enter_context(patch.object(build, 'require_managed_namespace'))
            stack.enter_context(patch.object(build, 'build_context', return_value=(b'inert archive', {})))
            stack.enter_context(patch.object(build.Path, 'read_text', return_value=json.dumps(dict(
                phase='inspection_required', base_image=build.BASE, network_denied_after=True,
                all_vms_stopped=True, cleanup_errors=[], build=dict(built=False, returncode=1),
                inputs={'old': 'recipe'}))))
            stack.enter_context(patch('builtins.open', mock_open()))
            stack.enter_context(patch.object(build.Path, 'open', mock_open()))
            stack.enter_context(patch.object(build.fcntl, 'flock'))
            stack.enter_context(patch.object(build.os, 'fsync'))
            stack.enter_context(patch.object(build, '_sync_directory'))
            stack.enter_context(patch.object(build.signal, 'signal'))
            stack.enter_context(patch.object(build.tempfile, 'mkdtemp', return_value='/synthetic/build'))
            stack.enter_context(patch.object(build, 'atomic_write_json',
                                            side_effect=lambda path, value: receipts.append(copy.deepcopy(value))))
            stack.enter_context(patch.object(build.policy, 'rules', side_effect=lambda: copy.deepcopy(rows)))
            stack.enter_context(patch.object(build.policy, 'scoped_deny',
                                            side_effect=lambda row: row['decision'] == 'deny'))
            stack.enter_context(patch.object(build.policy, 'allowed', side_effect=allowed))
            stopped = stack.enter_context(patch.object(build.policy, 'stopped'))
            stack.enter_context(patch.object(build.policy, 'run', side_effect=run))
            stack.enter_context(patch('sys.stdout', io.StringIO()))
            if fail_exec or fail_restore:
                with self.assertRaises(RuntimeError):
                    build.main()
            else:
                build.main()
        return calls, receipts[-1], rows, stopped.call_count

    def test_build_failure_restores_deny_before_removing_owned_allow(self):
        calls, receipt, rows, stops = self.scenario()
        restore = next(i for i, call in enumerate(calls) if call[:3] == ('policy', 'deny', 'network'))
        removal = next(i for i, call in enumerate(calls) if call[:3] == ('policy', 'rm', 'network')
                       and call[-1] == 'owned-allow')
        self.assertLess(restore, removal)
        self.assertTrue(receipt['network_denied_after'])
        self.assertTrue(receipt['all_vms_stopped'])
        self.assertEqual(receipt['cleanup_errors'], [])
        self.assertEqual(receipt['phase'], 'inspection_required')
        self.assertEqual(rows, [rule('restored-deny', 'deny', ['**'])])
        self.assertEqual(stops, 2)

    def test_restore_failure_still_stops_vm_and_preserves_unknown_state(self):
        calls, receipt, _, stops = self.scenario(fail_restore=True)
        self.assertIn(('stop', 'e-base-validation'), calls)
        self.assertEqual(receipt['phase'], 'inspection_required')
        self.assertIn('network_cleanup', receipt['cleanup_errors'])
        self.assertFalse(any(call[:3] == ('policy', 'rm', 'network') and call[-1] == 'owned-allow'
                             for call in calls))
        self.assertEqual(stops, 2)

    def test_success_also_restores_network_without_image_deletion(self):
        calls, receipt, _, _ = self.scenario(fail_exec=False)
        self.assertTrue(receipt['build']['built'])
        self.assertEqual(receipt['base_image'], build.BASE)
        self.assertTrue(receipt['network_denied_after'])
        self.assertFalse(any('rmi' in call or 'prune' in call for call in calls))


if __name__ == '__main__':
    unittest.main()
