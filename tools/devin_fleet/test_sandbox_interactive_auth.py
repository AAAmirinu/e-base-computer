"""Mock-only authentication launcher checks; never open a VM or log in."""
import os
from copy import deepcopy
import subprocess
import unittest
from unittest.mock import Mock, call, patch

if os.name == 'posix':
    import interactive_machine_auth as auth
    import launch_machine_auth as launcher


@unittest.skipUnless(os.name == 'posix', 'Dedicated Linux controller')
class InteractiveAuthTests(unittest.TestCase):
    def test_role_mapping_is_exact_and_uuid_pinned(self):
        expected = {
            'machine': '40e32a36-d565-4853-a841-fa3bea9ac648',
            'coordinator': '90cd1b4d-d8b6-4199-9e86-ddf1e59ba552',
            'toolchain': 'af53960e-7353-4c53-8d1d-9b4ead8fefb0',
            'kernel': 'ee03f652-9756-467c-9523-0764b1f42d6a',
            'stdlib': '53309df1-bbf5-4aa7-9614-b6159d607d6c',
            'storage': 'd401d8a1-edd4-460f-ba01-2e2a20fd46f3',
            'services': 'af3020c9-4112-41a6-bfba-baa866dea34e',
            'applications': '4cacfd64-5b54-4704-b636-dd101e35dd5b',
            'devtools': '16d99bbc-2821-48e5-97fa-02084f75c11e',
            'assurance': '7e7b1e74-d779-452d-9287-1101ab3ea19e',
        }
        self.assertEqual(auth.LOGIN_TARGETS, expected)
        self.assertEqual(set(launcher.LOGIN_ROLES), set(expected))
        with patch.object(auth, 'NAME', auth.NAME), patch.object(auth, 'UUID', auth.UUID):
            for role, identity in expected.items():
                auth.select_login_target(role)
                self.assertEqual((auth.NAME, auth.UUID), ('e-base-'+role, identity))

    def test_unknown_role_rejected_without_target_or_process_mutation(self):
        original = (auth.NAME, auth.UUID)
        with patch.object(auth, 'run') as run, patch.object(auth.subprocess, 'Popen') as spawn:
            for role in (None, [], '', 'validation', 'e-base-machine', 'machine ', '../machine',
                         'machine; true', '--catalog-check'):
                with self.subTest(role=role), self.assertRaises(ValueError):
                    auth.select_login_target(role)
                self.assertEqual((auth.NAME, auth.UUID), original)
        run.assert_not_called()
        spawn.assert_not_called()

    def test_coordinator_policy_helpers_use_only_selected_scope(self):
        with patch.object(auth, 'NAME', auth.NAME), patch.object(auth, 'UUID', auth.UUID):
            auth.select_login_target('coordinator')
            with patch.object(auth, 'run', side_effect=['{"rules":[]}', '{"allowed":false}']) as run:
                self.assertEqual(auth.rules(), [])
                self.assertIs(auth.allowed('example.com:443'), False)
            self.assertEqual(run.call_args_list, [
                call('policy', 'ls', 'e-base-coordinator', '--json'),
                call('policy', 'check', 'network', '--sandbox', 'e-base-coordinator',
                     '--json', 'example.com:443', allowed=(0, 1)),
            ])
            row = self.policy_fixture()[0]
            self.assertTrue(auth.scoped_deny(row))
            for key in ('scope', 'applies_to'):
                self.assertFalse(auth.scoped_deny(dict(row, **{key: 'sandbox:e-base-machine'})))

    def test_coordinator_stopped_requires_pinned_identity(self):
        with patch.object(auth, 'NAME', auth.NAME), patch.object(auth, 'UUID', auth.UUID):
            auth.select_login_target('coordinator')
            rows = [{'name':'e-base-'+role, 'id':identity, 'status':'stopped'}
                    for role, identity in auth.LOGIN_TARGETS.items()]
            rows.append({'name':'e-base-validation', 'id':'validation', 'status':'stopped'})
            import json
            with patch.object(auth, 'run', return_value=json.dumps({'sandboxes':rows})):
                auth.stopped()
            rows[1]['id'] = '40e32a36-d565-4853-a841-fa3bea9ac648'
            with patch.object(auth, 'run', return_value=json.dumps({'sandboxes':rows})):
                with self.assertRaises(RuntimeError):
                    auth.stopped()

    def test_coordinator_recovery_adds_only_selected_blanket_deny(self):
        with patch.object(auth, 'NAME', auth.NAME), patch.object(auth, 'UUID', auth.UUID):
            auth.select_login_target('coordinator')
            row = self.policy_fixture()[0]
            with patch.object(auth, 'stopped'), patch.object(auth, 'rules', side_effect=[[], [row]]), \
                    patch.object(auth, 'allowed', return_value=False), patch.object(auth, 'run') as run:
                result = auth.recover_machine_denial()
            run.assert_called_once_with('policy', 'deny', 'network', '--sandbox', 'e-base-coordinator', '**')
            self.assertEqual(result['sandbox_id'], auth.LOGIN_TARGETS['coordinator'])
            self.assertFalse(result['rules_removed'])
            self.assertFalse(result['resume_available'])

    def test_root_role_login_cannot_bypass_any_terminal_descriptor(self):
        for redirected in (0, 1, 2):
            with self.subTest(redirected=redirected), \
                    patch.object(launcher.sys, 'argv', ['launcher', '--login-role', 'coordinator']), \
                    patch.object(launcher.os, 'getuid', return_value=0), \
                    patch.dict(launcher.os.environ, {'WSL_DISTRO_NAME':'EBase-Sandboxes'}), \
                    patch.object(launcher.os, 'isatty', side_effect=lambda fd: fd != redirected), \
                    patch.object(launcher.Path, 'read_bytes') as read, \
                    patch.object(launcher.subprocess, 'run') as run, \
                    patch.object(launcher.subprocess, 'Popen') as spawn:
                with self.assertRaisesRegex(RuntimeError, 'private interactive terminal'):
                    launcher.main()
                read.assert_not_called()
                run.assert_not_called()
                spawn.assert_not_called()

    def test_root_role_login_rejects_arbitrary_arguments_before_actions(self):
        for args in (['--login-role'], ['--login-role', 'validation'],
                     ['--login-role', 'coordinator', '--catalog-check'],
                     ['--login-role', 'coordinator', '--uuid', 'other'],
                     ['--login-role', 'machine; true'], ['--login-role', '../machine'],
                     ['--recover-role', 'validation'], ['--recover-role', 'machine', '--login-role']):
            with self.subTest(args=args), patch.object(launcher.sys, 'argv', ['launcher']+args), \
                    patch.object(launcher.Path, 'read_bytes') as read, \
                    patch.object(launcher.subprocess, 'run') as run, \
                    patch.object(launcher.subprocess, 'Popen') as spawn:
                with self.assertRaisesRegex(RuntimeError, 'Unknown action'):
                    launcher.main()
                read.assert_not_called()
                run.assert_not_called()
                spawn.assert_not_called()

    def test_recovery_existing_deny_is_idempotent(self):
        row = {'resource_type':'network', 'decision':'deny', 'status':'active',
               'editable':True, 'scope':'sandbox:'+auth.NAME,
               'applies_to':'sandbox:'+auth.NAME, 'resources':['**']}
        with patch.object(auth, 'stopped') as stopped, patch.object(auth, 'rules', return_value=[row]), \
                patch.object(auth, 'allowed', return_value=False), patch.object(auth, 'run') as run:
            result = auth.recover_machine_denial()
        run.assert_not_called()
        self.assertEqual(stopped.call_count, 2)
        self.assertFalse(result['added_blanket_deny'])
        self.assertFalse(result['resume_available'])

    def test_recovery_missing_deny_adds_only_machine_blanket(self):
        row = {'resource_type':'network', 'decision':'deny', 'status':'active',
               'editable':True, 'scope':'sandbox:'+auth.NAME,
               'applies_to':'sandbox:'+auth.NAME, 'resources':['**']}
        with patch.object(auth, 'stopped'), patch.object(auth, 'rules', side_effect=[[], [row]]), \
                patch.object(auth, 'allowed', return_value=False), patch.object(auth, 'run') as run:
            result = auth.recover_machine_denial()
        run.assert_called_once_with('policy', 'deny', 'network', '--sandbox', auth.NAME, '**')
        self.assertTrue(result['added_blanket_deny'])
        self.assertFalse(result['rules_removed'])

    def test_recovery_running_vm_blocks_all_mutation(self):
        with patch.object(auth, 'stopped', side_effect=RuntimeError('running')), \
                patch.object(auth, 'rules') as rules, patch.object(auth, 'run') as run:
            with self.assertRaises(RuntimeError):
                auth.recover_machine_denial()
        rules.assert_not_called()
        run.assert_not_called()

    def test_recovery_does_not_accept_unverified_denial(self):
        with patch.object(auth, 'stopped'), patch.object(auth, 'rules', return_value=[]), \
                patch.object(auth, 'allowed', return_value=False), patch.object(auth, 'run'):
            with self.assertRaisesRegex(RuntimeError, 'blanket denial'):
                auth.recover_machine_denial()

    def test_redirected_stderr_refuses_before_guard_or_process(self):
        with patch.object(auth.os, 'isatty', side_effect=lambda fd: fd != 2) as tty, \
                patch.object(auth, 'require_managed_namespace') as guard, \
                patch.object(auth.subprocess, 'Popen') as spawn:
            with self.assertRaisesRegex(RuntimeError, 'Private user-operated terminal'):
                auth.main()
        self.assertEqual(tty.call_args_list, [call(0), call(1), call(2)])
        guard.assert_not_called()
        spawn.assert_not_called()

    def test_maintenance_timeout_kills_and_reaps_owned_group(self):
        process = Mock(pid=123)
        process.communicate.side_effect = [subprocess.TimeoutExpired('probe', 30), ('', '')]
        with patch.object(auth.subprocess, 'Popen', return_value=process) as spawn, \
                patch.object(auth.os, 'killpg') as kill:
            with self.assertRaises(subprocess.TimeoutExpired):
                auth.run('policy', 'ls', auth.NAME, '--json')
        self.assertTrue(spawn.call_args.kwargs['start_new_session'])
        kill.assert_called_once_with(123, auth.signal.SIGKILL)
        self.assertEqual(process.communicate.call_args_list, [call(timeout=30), call(timeout=5)])

    def test_vanished_group_still_reaped(self):
        process = Mock(pid=123)
        process.communicate.side_effect = [subprocess.TimeoutExpired('probe', 30), ('', '')]
        with patch.object(auth.subprocess, 'Popen', return_value=process), \
                patch.object(auth.os, 'killpg', side_effect=ProcessLookupError):
            with self.assertRaises(subprocess.TimeoutExpired):
                auth.run('policy', 'ls', auth.NAME, '--json')
        self.assertEqual(process.communicate.call_count, 2)

    def test_scope_is_exact_auth_https_without_package_or_cdn_hosts(self):
        self.assertEqual(auth.HOSTS, {
            'api.devin.ai:443', 'app.devin.ai:443', 'server.codeium.com:443'})
        self.assertEqual(auth.NAME, 'e-base-machine')
        self.assertEqual(auth.UUID, '40e32a36-d565-4853-a841-fa3bea9ac648')
        self.assertFalse(any('*' in host for host in auth.HOSTS))

    def test_policy_denial_code_requires_explicit_acceptance(self):
        process = Mock(returncode=1)
        process.communicate.return_value = ('{"allowed":false}', '')
        with patch.object(auth.subprocess, 'Popen', return_value=process):
            with self.assertRaises(RuntimeError):
                auth.run('policy')
            self.assertIs(auth.allowed('example.com:443'), False)

    def policy_fixture(self):
        deny = {'id': 'baseline', 'policy_id': 'local', 'editable': True,
                'resource_type': 'network', 'decision': 'deny', 'status': 'active',
                'scope': 'sandbox:'+auth.NAME, 'applies_to': 'sandbox:'+auth.NAME,
                'resources': ['**']}
        kit = dict(deny, id='kit-before', policy_id='kit-policy-before', editable=False,
                   decision='allow', resources=sorted(auth.HOSTS)+['cli.devin.ai:443'])
        return [deny, kit]

    def restriction(self, identity, resources):
        return dict(self.policy_fixture()[0], id=identity, resources=resources)

    def test_kit_view_identity_churn_does_not_become_cleanup_ownership(self):
        before = self.policy_fixture()
        after = deepcopy(before)
        after[1].update(id='kit-after', policy_id='kit-policy-after')
        after.append(self.restriction('owned', ['cli.devin.ai:443']))
        self.assertEqual(auth.restriction_ids(before, after, ['cli.devin.ai:443']), ['owned'])

    def test_multiple_created_rows_provide_exact_combined_coverage(self):
        before = self.policy_fixture()
        blocked = ['cli.devin.ai:443', 'static.devin.ai:443']
        after = deepcopy(before)+[self.restriction('first', blocked[:1]),
                                  self.restriction('second', blocked[1:])]
        self.assertEqual(auth.restriction_ids(before, after, blocked), ['first', 'second'])

    def test_existing_matching_restrictions_are_preserved_not_owned(self):
        blocked = ['cli.devin.ai:443', 'static.devin.ai:443']
        before = self.policy_fixture()+[self.restriction('existing', blocked[:1])]
        after = deepcopy(before)+[self.restriction('owned', blocked[1:])]
        self.assertEqual(auth.restriction_ids(before, after, blocked), ['owned'])
        self.assertEqual(auth.restriction_ids(after, deepcopy(after), blocked), [])

    def test_unexpected_editable_rows_are_rejected(self):
        before = self.policy_fixture()
        variants = [{'decision': 'allow'}, {'scope': 'sandbox:e-base-kernel'},
                    {'applies_to': 'sandbox:e-base-kernel'}, {'status': 'inactive'},
                    {'resource_type': 'filesystem'}, {'resources': ['**']},
                    {'resources': []}, {'resources': ['api.devin.ai:443']}]
        for changes in variants:
            with self.subTest(changes=changes):
                new = self.restriction('owned', ['cli.devin.ai:443'])
                new.update(changes)
                with self.assertRaisesRegex(RuntimeError, 'Unexpected new editable policy'):
                    auth.restriction_ids(before, deepcopy(before)+[new], ['cli.devin.ai:443'])

    def test_missing_restriction_coverage_is_rejected(self):
        before = self.policy_fixture()
        after = deepcopy(before)+[self.restriction('owned', ['cli.devin.ai:443'])]
        with self.assertRaisesRegex(RuntimeError, 'coverage incomplete'):
            auth.restriction_ids(before, after, ['cli.devin.ai:443', 'static.devin.ai:443'])

    def test_changed_or_removed_existing_editable_rule_is_rejected(self):
        before = self.policy_fixture()
        for changes in ({'resources': ['example.com:443']}, {'policy_id': 'changed'},
                        {'id': 'replaced'}):
            with self.subTest(changes=changes):
                after = deepcopy(before)
                after[0].update(changes)
                with self.assertRaisesRegex(RuntimeError, 'Existing policy changed'):
                    auth.restriction_ids(before, after, [])
        with self.assertRaisesRegex(RuntimeError, 'Existing policy changed'):
            auth.restriction_ids(before, deepcopy(before[1:]), [])

    def test_kit_resource_change_is_not_masked_by_identity_churn(self):
        before = self.policy_fixture()
        after = deepcopy(before)
        after[1].update(id='kit-after', policy_id='kit-policy-after')
        after[1]['resources'].append('unexpected.example:443')
        with self.assertRaisesRegex(RuntimeError, 'Existing policy changed'):
            auth.restriction_ids(before, after, [])

    def test_duplicate_editable_identity_is_rejected(self):
        before = self.policy_fixture()
        after = deepcopy(before)+[deepcopy(before[0])]
        with self.assertRaisesRegex(RuntimeError, 'Duplicate editable rule identity'):
            auth.restriction_ids(before, after, [])


if __name__ == '__main__':
    unittest.main()
