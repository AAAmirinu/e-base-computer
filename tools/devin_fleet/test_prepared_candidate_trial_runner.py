from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import os
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

if os.name == 'nt':
    sys.modules.setdefault('fcntl', Mock())
    sys.modules.setdefault('resource', Mock())

import prepared_candidate_trial_guards as guards
import prepared_candidate_trial_runner as runner


class PreparedCandidateTrialRunnerTests(unittest.TestCase):
    def setUp(self):
        self.registration = {
            'production_enabled': True,
            'controller_root': '/home/fleet/controller-validation/trial/controller',
            'roles': {'machine': {'image_digest': 'sha256:' + 'a' * 64}},
        }
        self.request = {
            'entry': {'paths': ['add.py']}, 'state': {'sessions': {}},
            'settings': {'turn_timeout_seconds': 300},
        }
        self.project = {'verified': True, 'production_admitted': False,
            'activated': False, 'model_executed': False,
            'task_request': self.request, 'head': 'b' * 40, 'tree': 'c' * 40,
            'bundle_sha256': hashlib.sha256(b'bundle').hexdigest(),
            'parent_ref': 'refs/heads/main'}

    def test_runner_wires_only_fixed_one_shot_adapters(self):
        fixed = {'admission': Mock(), 'network_scope': Mock()}
        with patch.object(runner.trial_state, 'runtime_registration', return_value=self.registration), \
             patch.object(runner.trial_state, 'CONTROLLER', Path(self.registration['controller_root'])), \
             patch.object(runner.trial_state, 'trial_guest_root', return_value='/trial/machine'), \
             patch.object(runner.trial_project, 'inspect', return_value=self.project), \
             patch.object(runner.trial_project, 'TASK_REQUEST', self.request), \
             patch.object(runner.trial_project, 'PROJECT', Path('/trusted/trial/project')), \
             patch.object(runner.trial_project, 'BUNDLE', Path('/trusted/trial/parent.bundle')), \
             patch.object(runner, '_require_seed_receipt'), \
             patch.object(runner, '_file', return_value=b'bundle'), \
             patch.object(runner.trial_guards, 'make_guards', return_value=fixed) as make_guards, \
             patch.object(runner, 'run_one_turn', return_value={'phase': 'pending_review'}) as turn:
            result = runner.run()
        self.assertEqual(result, {'phase': 'pending_review'})
        make_guards.assert_called_once_with(self.registration, 'machine',
            self.request['entry'], self.request['settings'])
        arguments = turn.call_args.kwargs
        self.assertEqual(arguments['project_root'], Path('/trusted/trial/project'))
        self.assertEqual(arguments['sequence'], 0)
        self.assertEqual(arguments['runtime_factory'].keywords['capacity'], 1)
        self.assertEqual(arguments['trial_guest_root'], '/trial/machine')
        self.assertIs(arguments['validate'], runner.trial_validation.validate)
        self.assertIs(arguments['admission'], fixed['admission'])
        candidate = arguments['build_and_import']
        self.assertIs(candidate.keywords['admission_factory'],
                      runner.trial_candidate_admission.make_admission)
        self.assertNotIn('publish', arguments)
        self.assertNotIn('resume', arguments)

    def test_inert_manifest_drift_stops_before_guards_or_turn(self):
        changed = dict(self.project, activated=True)
        with patch.object(runner.trial_state, 'runtime_registration', return_value=self.registration), \
             patch.object(runner.trial_project, 'inspect', return_value=changed), \
             patch.object(runner, '_require_seed_receipt'), \
             patch.object(runner.trial_guards, 'make_guards') as make_guards, \
             patch.object(runner, 'run_one_turn') as turn:
            with self.assertRaises(ValueError):
                runner.run()
        make_guards.assert_not_called()
        turn.assert_not_called()

    def test_preflight_is_read_only_and_creates_no_cycle(self):
        repo = Mock()
        lease = Mock()
        lease.__enter__ = Mock(return_value=repo)
        lease.__exit__ = Mock(return_value=False)
        runtime = Mock()
        runtime.__enter__ = Mock(return_value=runtime)
        runtime.__exit__ = Mock(return_value=False)
        runtime.role.return_value = lease
        with patch.object(runner.trial_state, 'runtime_registration', return_value=self.registration), \
             patch.object(runner.trial_state, 'CONTROLLER', Path(self.registration['controller_root'])), \
             patch.object(runner.trial_state, 'trial_guest_root', return_value='/trial/machine'), \
             patch.object(runner.trial_project, 'inspect', return_value=self.project), \
             patch.object(runner, '_require_seed_receipt'), \
             patch.object(runner, 'PreparedCandidateTrialRuntime', return_value=runtime), \
             patch.object(runner.trial_guards, '_verify_guest_parent') as verify, \
             patch.object(runner, 'run_one_turn') as turn:
            result = runner.preflight()
        repo.restrict_git_to_model_reads.assert_called_once_with()
        verify.assert_called_once_with(repo, self.project)
        turn.assert_not_called()
        self.assertFalse(result['network_opened'])
        self.assertFalse(result['cycle_created'])

    def test_seed_receipt_is_exact_and_fail_closed(self):
        controller = Path('/trusted/controller')
        expected = {'schema': 1, 'phase': 'complete', 'role': 'machine',
            'retry': False, 'resume_available': False, 'activated': False,
            'published': False, 'bundle_sha256': self.project['bundle_sha256'],
            'head': self.project['head'], 'tree': self.project['tree'],
            'all_vms_stopped': True}
        with patch.object(runner.trial_state, 'CONTROLLER', controller), \
             patch.object(runner, '_file', return_value=json.dumps(expected).encode()):
            self.assertEqual(runner._require_seed_receipt(self.project), expected)
        for changed in (dict(expected, phase='inspection_required'),
                        dict(expected, all_vms_stopped=False),
                        dict(expected, extra=True)):
            with self.subTest(changed=changed), \
                 patch.object(runner.trial_state, 'CONTROLLER', controller), \
                 patch.object(runner, '_file', return_value=json.dumps(changed).encode()), \
                 self.assertRaisesRegex(ValueError, 'Exact completed'):
                runner._require_seed_receipt(self.project)


class PreparedCandidateTrialGuardTests(unittest.TestCase):
    def test_guest_parent_exact_check_is_read_only(self):
        files = {'add.py': b'broken', 'test_add.py': b'test'}
        project = {'head': 'a' * 40, 'tree': 'b' * 40}
        repo = Mock()
        repo.guest_root='/trial/machine'
        repo.git.side_effect = [project['head'], project['tree'],
                                'add.py\0test_add.py\0']
        repo.fingerprint.side_effect = lambda path: hashlib.sha256(files[path]).hexdigest()
        with patch.object(guards.trial_project, 'FILES', files), \
             patch.object(guards.trial_state, 'trial_guest_root', return_value='/trial/machine'), \
             patch.object(guards.fleet, 'changes', return_value=[]):
            guards._verify_guest_parent(repo, project)
        self.assertFalse(any(call.args and call.args[0] in
            ('checkout', 'clone', 'reset', 'clean') for call in repo.git.call_args_list))
        repo.write_bytes.assert_not_called()

    def test_guest_parent_drift_fails_without_mutation(self):
        repo = Mock()
        repo.guest_root='/trial/machine'
        repo.git.return_value = 'wrong'
        with patch.object(guards.trial_state, 'trial_guest_root', return_value='/trial/machine'), \
             self.assertRaises(ValueError):
                guards._verify_guest_parent(repo, {'head': 'a' * 40, 'tree': 'b' * 40})
        repo.write_bytes.assert_not_called()

    def test_guard_uses_exact_trial_checker_and_precondition(self):
        registration = {'roles': {'machine': {'image_digest': 'sha256:' + 'a' * 64}}}
        request = {'entry': {'paths': ['add.py']}, 'state': {}, 'settings': {'x': 1}}
        project = dict(request and {'task_request': request, 'head': 'h', 'tree': 't'})
        base = Mock(return_value={'stage': 'before_prepare'})
        with patch.object(guards.trial_project, 'inspect', return_value=project), \
             patch.object(guards.trial_state, 'runtime_registration', return_value=registration), \
             patch.object(guards.trial_state, 'trial_guest_root', return_value='/trial/machine'), \
             patch.object(guards, 'make_model_admission', return_value=base) as factory, \
             patch.object(guards, 'close_catalog_access') as close_catalog, \
             patch.object(guards, '_verify_guest_parent') as verify:
            made = guards.make_guards(registration, 'machine', request['entry'], request['settings'])
            repo = Mock()
            result = made['admission'](Mock(), 'machine', request['settings'],
                stage='before_prepare', repo=repo, prepared=None, timeout=10)
        self.assertEqual(result, {'stage': 'before_prepare'})
        self.assertIs(factory.call_args.kwargs['registration_check'],
                      guards.trial_state.check_runtime_registration)
        verify.assert_called_once_with(repo, project)
        close_catalog.assert_not_called()


if __name__ == '__main__':
    unittest.main()
