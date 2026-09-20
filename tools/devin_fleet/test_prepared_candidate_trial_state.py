import json
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch

import prepared_candidate_trial_state as trial
import production_registration_candidate as candidate
import production_registration_prepare as prep


class TrialStateTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.prep_run = self.root / 'production-registration-preparation-v1'
        self.previous = self.root / 'production-registration-trial-v10'
        self.run = self.root / 'production-registration-trial-v11'
        patches = (
            (candidate, 'ROOT', self.root), (prep, 'ROOT', self.root),
            (prep, 'RUN', self.prep_run), (trial, 'ROOT', self.root),
            (trial, 'PREVIOUS_RUN', self.previous),
            (trial, 'RUN', self.run), (trial, 'STATE', self.run / 'state'),
            (trial, 'CONTROLLER', self.run / 'controller'),
        )
        for target, name, value in patches:
            p = patch.object(target, name, value); p.start(); self.addCleanup(p.stop)
        for target in (prep, trial):
            p = patch.object(target, 'require_managed_namespace', return_value=None)
            p.start(); self.addCleanup(p.stop)
            p = patch.object(target, 'global_lock_held', return_value=True)
            p.start(); self.addCleanup(p.stop)
        roles = {role: {'id': str(uuid.uuid5(uuid.NAMESPACE_DNS, role)),
                        'name': 'e-base-' + role} for role in candidate.ROLES}
        value = {'schema': 1, 'distro': 'EBase-Sandboxes', 'user': 'fleet',
                 'resources_per_sandbox': {'cpus': 2, 'memory': '4g'},
                 'roles': roles, 'simultaneous_capacity_verified': 1,
                 'production_enabled': False}
        (self.root / 'sandbox-registry.json').write_text(json.dumps(value))
        (self.root / 'sandbox-registry.json').chmod(0o600)
        prep.prepare()
        state=self.previous/'state';state.mkdir(parents=True)
        (state/'commit.json').write_text(json.dumps({'phase':'complete'}))
        path=self.previous/'controller'/'cycles'/'fixed-inert-one-turn-v11'
        path.mkdir(parents=True)
        (path/'cycle.json').write_text(json.dumps({
            'phase':'held','interrupted_phase':'model_pending',
            'error_type':'ValueError','published':False,
            'model_retry_allowed':False,'resume_available':False}))

    def test_prepare_copies_candidate_and_derives_only_controller_root(self):
        active_before = (self.root / 'sandbox-registry.json').read_bytes()
        candidate_before = (self.prep_run / 'candidate.json').read_bytes()
        result = trial.prepare()
        self.assertEqual(result, trial.inspect())
        self.assertEqual(candidate_before, (self.run / 'state' / 'candidate.json').read_bytes())
        original = json.loads(candidate_before)
        registration = json.loads((self.run / 'state' / 'registration.json').read_bytes())
        changed = {key for key in original if original[key] != registration[key]}
        self.assertEqual(changed, {'controller_root'})
        self.assertEqual(registration['controller_root'], str(self.run / 'controller'))
        self.assertEqual(active_before, (self.root / 'sandbox-registry.json').read_bytes())
        for key in ('automatic_resume', 'retry', 'activated', 'published'):
            self.assertIs(result[key], False)
        with self.assertRaises(FileExistsError):
            trial.prepare()

    def test_extra_controller_entry_and_raw_drift_are_rejected(self):
        trial.prepare()
        (self.run / 'controller' / 'cycles' / 'unexpected').touch()
        with self.assertRaises(ValueError):
            trial.inspect()
        self.assertEqual(trial.runtime_registration()['controller_root'],
                         str(self.run/'controller'))
        (self.run/'controller'/'unexpected').mkdir()
        with self.assertRaises(ValueError):
            trial.inspect(runtime=True)

    def test_active_or_prepared_drift_is_rejected(self):
        trial.prepare()
        active = self.root / 'sandbox-registry.json'
        active.write_bytes(active.read_bytes() + b' ')
        with self.assertRaises(ValueError):
            trial.inspect()

    def test_partial_state_is_not_resumed(self):
        self.run.mkdir()
        with self.assertRaises(FileExistsError):
            trial.prepare()
        with self.assertRaises((ValueError, FileNotFoundError)):
            trial.inspect()

    def test_symlink_or_extra_state_entry_is_rejected(self):
        trial.prepare()
        (self.run / 'state' / 'extra').touch()
        with self.assertRaises(ValueError):
            trial.inspect()

    def test_lock_required_before_reservation(self):
        with patch.object(trial, 'global_lock_held', return_value=False):
            with self.assertRaises(ValueError):
                trial.prepare()
        self.assertFalse(self.run.exists())

    def test_runtime_registration_callback_rechecks_binding(self):
        trial.prepare()
        registration=trial.runtime_registration()
        self.assertIsNone(trial.check_runtime_registration(registration))
        registration['migration_epoch']='changed'
        with self.assertRaises(ValueError):
            trial.check_runtime_registration(registration)
        registration=trial.runtime_registration()
        registration['simultaneous_capacity_verified']=True
        with self.assertRaises(ValueError):
            trial.check_runtime_registration(registration)


if __name__ == '__main__':
    unittest.main()
