"""Two-lease model-phase contracts. No actual model or host project execution."""
from contextlib import contextmanager
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

import fleet
import sandbox_turn
from sandbox_repository import GuestRepository

EPOCH = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'


class Runtime:
    def __init__(self, root, events):
        self.stop_path = root / 'STOP'
        self.registration = {'backend': 'sandbox', 'migration_epoch': EPOCH,
                             'controller_root': str(root),
                             'production_enabled': True,
                             'roles': {'machine': {'name': 'e-base-machine',
                                       'id': 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'},
                                       'coordinator': {'name': 'e-base-coordinator',
                                       'id': 'cccccccc-cccc-4ccc-8ccc-cccccccccccc'}}}
        self.events = events
        self.count = 0
        self.fail_exit = None
        self.repos = []

    @contextmanager
    def role(self, role):
        self.count += 1
        number = self.count
        self.events.append(('enter', number))
        repo = Mock(spec=GuestRepository)
        repo.guest_root = '/home/agent/workspace/' + role
        repo.controller = Mock()
        repo.controller.name = self.registration['roles'][role]['name']
        repo.controller.sandbox_id = self.registration['roles'][role]['id']
        repo.external_stop = self.stop_path
        self.repos.append(repo)
        try:
            yield repo
        finally:
            self.events.append(('stop', number))
            if self.fail_exit == number:
                raise RuntimeError('VM stop failed')


class ModelPhaseTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.run_dir = self.root / 'fresh-run'
        self.events = []
        self.runtime = Runtime(self.root, self.events)
        self.entry = {'paths': ['src/**']}
        self.state = {'round': 7, 'reports': {}, 'candidates': {}, 'sessions': {}}
        self.settings = {'turn_timeout_seconds': 30}
        self.staged = {'args': ['devin', '--config', '/guest/config'],
                       'extra_files_sha256': {},
                       'config_sha256': 'a' * 64, 'prompt_sha256': 'b' * 64,
                       'relative': '.fleet/control-example', 'base': 'a' * 40,
                       'role': 'machine', 'round': 7}
        self.export = {'session_id': 'new-session',
                       'steps': [{'source': 'agent', 'model_name': 'swe-2-high'}]}
        self.admission = Mock(side_effect=self.admit)
        self.prepare = self.install('prepare_guest_turn', side_effect=self.stage)
        self.execute = self.install('execute_model_attempt', side_effect=self.model)
        self.read = self.install('read_repository_json', side_effect=self.read_report)
        self.changes = self.install('changes', side_effect=lambda *args: ['src/a.py'])
        self.owned = self.install('check_owned_changes')
        self.fingerprints = self.install('fingerprints', return_value={'src/a.py': 'c' * 64})
        self.install('sha', return_value='a' * 40)
        self.source_snapshot = {'manifest_sha256': 'd' * 64,
                                'manifest': {'base': 'a' * 40, 'files': [{'path': 'src/a.py', 'size': 4,
                                                        'sha256': 'c' * 64}]}}
        capture_guard = patch.object(sandbox_turn, 'capture_source_snapshot', side_effect=self.capture_snapshot)
        self.capture = capture_guard.start()
        self.addCleanup(capture_guard.stop)
        persist_guard = patch.object(sandbox_turn, 'persist_source_snapshot', side_effect=self.persist_snapshot)
        self.persist = persist_guard.start()
        self.addCleanup(persist_guard.stop)
        for name in ('subprocess.run', 'subprocess.Popen', 'os.system'):
            guard = patch(name, side_effect=AssertionError('Host execution forbidden'))
            guard.start()
            self.addCleanup(guard.stop)
        self.install('validate_repository', side_effect=AssertionError('Validation not admitted'))

    def install(self, name, **kwargs):
        guard = patch.object(fleet, name, **kwargs)
        result = guard.start()
        self.addCleanup(guard.stop)
        return result

    def stage(self, *args, **kwargs):
        self.events.append('stage')
        return self.staged

    def admit(self, runtime, role, settings, *, stage, repo, prepared, timeout):
        self.events.append(('admit', stage))
        self.assertIs(runtime, self.runtime)
        self.assertIs(settings, self.settings)
        self.assertGreater(timeout, 0)
        self.assertLessEqual(timeout, self.settings['turn_timeout_seconds'])
        if stage == 'initial':
            self.assertIsNone(repo)
            self.assertIsNone(prepared)
        elif stage == 'before_inspection':
            self.assertIs(repo, self.runtime.repos[1])
            self.assertIsNone(prepared)
            self.assertIn(('stop', 1), self.events)
            self.assertNotIn(('stop', 2), self.events)
            self.read.assert_not_called()
        else:
            self.assertIs(repo, self.runtime.repos[0])
            self.assertNotIn(('stop', 1), self.events)
            if stage == 'before_prepare':
                self.assertIsNone(prepared)
                self.prepare.assert_not_called()
            else:
                self.assertEqual(stage, 'before_model')
                self.assertIs(prepared, self.staged)

    def model(self, *args, **kwargs):
        self.events.append('model')
        return subprocess.CompletedProcess([], 0), self.export

    def read_report(self, repo, path, *args, **kwargs):
        self.events.append(('read', path))
        return {'summary': 'review me'} if 'report' in path else {'accept': []}

    def capture_snapshot(self, repo, snapshot):
        self.events.append('capture')
        self.assertIs(repo, self.runtime.repos[1])
        self.assertIn(('enter', 2), self.events)
        self.assertNotIn(('stop', 2), self.events)
        self.assertEqual(snapshot, {'base': 'a' * 40, 'changed': ['src/a.py'],
                                    'fingerprints': {'src/a.py': 'c' * 64}})
        return self.source_snapshot

    def persist_snapshot(self, directory, snapshot):
        self.events.append('persist')
        self.assertIn(('stop', 2), self.events)
        self.assertEqual(directory, self.run_dir / 'source-snapshot')
        self.assertIs(snapshot, self.source_snapshot)
        self.assertFalse((self.run_dir / 'checkpoint.json').exists())

    def invoke(self, **overrides):
        args = dict(runtime=self.runtime, root=self.root, role='machine', entry=self.entry,
                    state=self.state, settings=self.settings, run_directory=self.run_dir,
                    admission=self.admission, sequence=0)
        args.update(overrides)
        return sandbox_turn.run_guest_model_phase(**args)

    def phases(self):
        return [json.loads(path.read_text()).get('phase')
                for path in self.run_dir.glob('*.json')]

    def test_network_window_wraps_admission_and_model_before_vm_stop(self):
        @contextmanager
        def scope(runtime,role,repo,directory,*,timeout):
            self.assertIs(runtime,self.runtime)
            self.assertIs(repo,self.runtime.repos[0])
            self.assertEqual(directory,self.run_dir/'network-window')
            self.assertGreater(timeout,0)
            self.events.append('network-open')
            try:
                yield
            finally:
                self.events.append('network-closed')
        self.invoke(network_scope=scope)
        self.assertLess(self.events.index('stage'),self.events.index('network-open'))
        self.assertLess(self.events.index('network-open'),self.events.index(('admit','before_model')))
        self.assertLess(self.events.index(('admit','before_model')),self.events.index('network-closed'))
        self.assertLess(self.events.index('network-closed'),self.events.index(('stop',1)))

    def test_network_cleanup_failure_stops_lease_and_blocks_inspection(self):
        @contextmanager
        def scope(*args,**kwargs):
            yield
            raise RuntimeError('synthetic close failure')
        with self.assertRaisesRegex(RuntimeError,'close failure'):
            self.invoke(network_scope=scope)
        self.assertEqual(self.execute.call_count,1)
        self.assertIn(('stop',1),self.events)
        self.assertEqual(self.runtime.count,1)
        self.capture.assert_not_called()
        self.assertTrue((self.root/'model-turn-fences'/'machine.json').exists())

    def test_invalid_network_scope_rejected_before_fence(self):
        with self.assertRaises(ValueError):
            self.invoke(network_scope=True)
        self.admission.assert_not_called()
        self.assertFalse((self.root/'model-turn-fences').exists())

    def test_feedback_forwarded_and_recorded_without_changing_admission(self):
        self.staged['validation_feedback_sha256'] = 'e'*64
        result = self.invoke(validation_feedback=b'evidence', validation_feedback_sha256='e'*64)
        self.assertEqual(self.prepare.call_args.kwargs['validation_feedback'], b'evidence')
        self.assertEqual(self.prepare.call_args.kwargs['validation_feedback_sha256'], 'e'*64)
        self.assertEqual(result['validation_feedback_sha256'], 'e'*64)
        self.assertEqual(self.admission.call_count, 4)

    def test_new_output_directory_cannot_bypass_awaiting_validation(self):
        result = self.invoke()
        reservation = json.loads((self.root/'model-turn-fences'/'machine.json').read_text())
        self.assertEqual(reservation['operation_id'], result['operation_id'])
        before = self.execute.call_count
        self.admission.reset_mock()
        with self.assertRaisesRegex(RuntimeError, 'Unresolved prior model turn'):
            self.invoke(run_directory=self.root/'new-after-restart', sequence=1)
        self.admission.assert_not_called()
        self.assertEqual(self.execute.call_count, before)

    def test_admission_failure_stays_fenced_after_runtime_restart(self):
        self.admission.side_effect = RuntimeError('admission incomplete')
        with self.assertRaisesRegex(RuntimeError, 'admission incomplete'):
            self.invoke()
        self.runtime = Runtime(self.root, self.events)
        self.admission.reset_mock()
        self.admission.side_effect = None
        with self.assertRaisesRegex(RuntimeError, 'Unresolved prior model turn'):
            self.invoke(run_directory=self.root/'retry')
        self.admission.assert_not_called()
        self.execute.assert_not_called()

    def test_unregistered_controller_root_refused_before_admission(self):
        self.runtime.registration['controller_root'] = str(self.root/'different-root')
        with self.assertRaises(ValueError):
            self.invoke()
        self.admission.assert_not_called()
        self.assertFalse((self.root/'model-turn-fences').exists())

    def test_feedback_does_not_bypass_disabled_production(self):
        self.runtime.registration['production_enabled'] = False
        with self.assertRaises(RuntimeError):
            self.invoke(validation_feedback=b'evidence', validation_feedback_sha256='e'*64)
        self.execute.assert_not_called()
        self.prepare.assert_not_called()

    def test_two_leases_stop_before_inspection_and_forward_exact_inputs(self):
        original = copy.deepcopy(self.state)
        result = self.invoke()
        self.assertEqual(result['phase'], 'awaiting_validation')
        self.assertEqual(self.runtime.count, 2)
        self.assertLess(self.events.index(('stop', 1)), self.events.index(('enter', 2)))
        self.assertLess(self.events.index(('enter', 2)), self.events.index(('read', '.fleet/report.json')))
        self.assertEqual(self.events[:5], [('admit', 'initial'), ('enter', 1),
            ('admit', 'before_prepare'), 'stage', ('admit', 'before_model')])
        calls = self.admission.call_args_list
        self.assertEqual([call.kwargs['stage'] for call in calls],
                         ['initial', 'before_prepare', 'before_model', 'before_inspection'])
        self.assertIs(calls[2].kwargs['repo'], self.runtime.repos[0])
        self.assertIs(calls[2].kwargs['prepared'], self.staged)
        self.assertIs(calls[3].kwargs['repo'], self.runtime.repos[1])
        self.assertIsNone(calls[3].kwargs['prepared'])
        self.assertGreater(calls[2].kwargs['timeout'], 0)
        self.assertLessEqual(calls[2].kwargs['timeout'], calls[0].kwargs['timeout'])
        self.assertEqual(self.execute.call_args.args[1], self.staged['args'])
        call = self.execute.call_args
        self.assertEqual(call.kwargs['expected_config_sha256'], 'a' * 64)
        self.assertEqual(call.kwargs['expected_prompt_sha256'], 'b' * 64)
        self.assertEqual(call.kwargs['expected_extra_files_sha256'], {})
        self.assertEqual(call.kwargs['migration_epoch'], EPOCH)
        self.assertEqual(call.kwargs['sequence'], 0)
        self.assertIs(self.read.call_args.args[0], self.runtime.repos[1])
        self.assertEqual(self.state, original)
        self.assertIn('awaiting_validation', self.phases())
        self.capture.assert_called_once()
        self.persist.assert_called_once()
        self.assertLess(self.events.index('capture'), self.events.index(('stop', 2)))
        self.assertLess(self.events.index(('stop', 2)), self.events.index('persist'))
        self.assertEqual(result['snapshot']['manifest_sha256'], 'd' * 64)
        checkpoint = json.loads((self.run_dir / 'checkpoint.json').read_text())
        self.assertEqual(checkpoint['snapshot'], result['snapshot'])
        capture = json.loads((self.run_dir / 'capture.json').read_text())
        for key in ('operation_id', 'migration_epoch', 'sequence', 'role', 'sandbox_id'):
            self.assertEqual(capture[key], result[key])
        self.assertEqual(capture['source_checkpoint'], result['snapshot'])
        self.assertEqual((capture['file_count'], capture['source_bytes'], capture['blob_count']), (1, 4, 1))
        self.assertIs(capture['source_vm_stopped'], True)
        self.assertIs(capture['source_executed'], False)
        from validation_snapshot_input import load_capture, load_turn_binding
        evidence = load_capture(self.run_dir/'capture.json', self.run_dir/'source-snapshot',
                                'd'*64, self.source_snapshot['manifest'], self.runtime.registration['roles'])
        binding = load_turn_binding(self.run_dir/'turn.json', evidence, expected_epoch=EPOCH)
        self.assertEqual(binding['operation_id'], result['operation_id'])
        self.assertEqual(binding['manifest_sha256'], result['snapshot']['manifest_sha256'])

    def test_initial_admission_failure_never_stages(self):
        self.admission.side_effect = RuntimeError('unverified free model')
        with self.assertRaises(RuntimeError):
            self.invoke()
        self.assertEqual(self.runtime.count, 0)
        self.prepare.assert_not_called()
        self.execute.assert_not_called()
        receipt = json.loads((self.run_dir / 'turn.json').read_text())
        self.assertEqual(receipt['phase'], 'held')
        self.assertEqual(receipt['admission_stage'], 'initial')
        self.assertEqual(receipt['admission_status'], 'incomplete')
        self.assertNotIn('unverified free model', json.dumps(receipt))

    def test_before_model_admission_failure_stops_without_model(self):
        self.admission.side_effect = [None, None, RuntimeError('catalog changed')]
        with self.assertRaises(RuntimeError):
            self.invoke()
        self.assertIn(('stop', 1), self.events)
        self.execute.assert_not_called()
        self.assertNotIn('awaiting_validation', self.phases())
        receipt = json.loads((self.run_dir / 'turn.json').read_text())
        self.assertEqual(receipt['phase'], 'held')
        self.assertEqual(receipt['admission_stage'], 'before_model')
        self.assertNotIn('catalog changed', json.dumps(receipt))

    def test_before_prepare_rejection_stops_lease_and_preserves_fence(self):
        self.admission.side_effect = [None, RuntimeError('unsafe guest repository')]
        with self.assertRaises(RuntimeError):
            self.invoke()
        self.prepare.assert_not_called()
        self.execute.assert_not_called()
        self.assertEqual(self.runtime.count, 1)
        self.assertIn(('stop', 1), self.events)
        receipt = json.loads((self.run_dir / 'turn.json').read_text())
        self.assertEqual(receipt['phase'], 'held')
        self.assertEqual(receipt['admission_stage'], 'before_prepare')
        self.assertEqual(receipt['admission_status'], 'incomplete')
        self.assertTrue((self.root / 'model-turn-fences' / 'machine.json').is_file())

    def test_before_inspection_rejection_stops_without_reading_or_capture(self):
        self.admission.side_effect = [None, None, None, RuntimeError('unsafe inspection repository')]
        with self.assertRaises(RuntimeError):
            self.invoke()
        self.execute.assert_called_once()
        self.read.assert_not_called()
        self.changes.assert_not_called()
        self.capture.assert_not_called()
        self.assertIn(('stop', 2), self.events)
        receipt = json.loads((self.run_dir / 'turn.json').read_text())
        self.assertEqual(receipt['phase'], 'held')
        self.assertEqual(receipt['admission_stage'], 'before_inspection')
        self.assertTrue((self.root / 'model-turn-fences' / 'machine.json').is_file())

    def test_interrupted_admission_records_hold_without_clearing_fence(self):
        self.admission.side_effect = KeyboardInterrupt('private diagnostic')
        with self.assertRaises(KeyboardInterrupt):
            self.invoke()
        raw = (self.run_dir / 'turn.json').read_text()
        self.assertNotIn('private diagnostic', raw)
        self.assertEqual(json.loads(raw)['phase'], 'held')
        self.assertTrue((self.root / 'model-turn-fences' / 'machine.json').exists())
        self.execute.assert_not_called()

    def test_admission_observes_durable_pending_state(self):
        observed = []
        def admit(*args, **kwargs):
            receipt = json.loads((self.run_dir / 'turn.json').read_text())
            observed.append((receipt['phase'], receipt['admission_stage'],
                             receipt['admission_status']))
        self.admission.side_effect = admit
        self.invoke()
        self.assertEqual(observed, [('awaiting_admission', 'initial', 'checking'),
                                    ('admitted', 'before_prepare', 'checking'),
                                    ('prepared', 'before_model', 'checking'),
                                    ('inspection_pending', 'before_inspection', 'checking')])

    def test_existing_stop_blocks_before_staging(self):
        self.runtime.stop_path.touch()
        with self.assertRaises(Exception):
            self.invoke()
        self.prepare.assert_not_called()
        self.assertTrue(self.runtime.stop_path.exists())

    def test_invalid_timeout_and_sequence_refused(self):
        for value in (0, -1, float('inf'), float('nan'), True, '30'):
            with self.subTest(timeout=value), self.assertRaises((ValueError, TypeError)):
                self.invoke(settings={'turn_timeout_seconds': value})
        for value in (-1, True, 1.5, '1'):
            with self.subTest(sequence=value), self.assertRaises((ValueError, TypeError)):
                self.invoke(sequence=value)
        self.prepare.assert_not_called()

    def test_legacy_session_not_adopted(self):
        self.state['sessions'] = {'machine': 'old-session'}
        with self.assertRaises((ValueError, RuntimeError)):
            self.invoke()
        self.prepare.assert_not_called()

    def test_production_disabled_blocks(self):
        self.runtime.registration['production_enabled'] = False
        with self.assertRaises((ValueError, RuntimeError)):
            self.invoke()
        self.prepare.assert_not_called()

    def test_first_stop_failure_never_inspects(self):
        self.runtime.fail_exit = 1
        with self.assertRaises(RuntimeError):
            self.invoke()
        self.read.assert_not_called()
        self.assertNotIn('awaiting_validation', self.phases())

    def test_second_stop_failure_never_records_awaiting_validation(self):
        self.runtime.fail_exit = 2
        with self.assertRaises(RuntimeError):
            self.invoke()
        self.assertNotIn('awaiting_validation', self.phases())
        self.capture.assert_called_once()
        self.persist.assert_not_called()
        self.assertFalse((self.run_dir / 'checkpoint.json').exists())
        self.assertIn('inspection_pending', self.phases())

    def test_capture_failure_stops_without_persisting_or_accepting(self):
        self.capture.side_effect = RuntimeError('source snapshot failed')
        with self.assertRaisesRegex(RuntimeError, 'source snapshot failed'):
            self.invoke()
        self.assertIn(('stop', 2), self.events)
        self.persist.assert_not_called()
        self.assertFalse((self.run_dir / 'checkpoint.json').exists())
        self.assertNotIn('awaiting_validation', self.phases())

    def test_persist_failure_never_records_awaiting_validation(self):
        self.persist.side_effect = RuntimeError('snapshot persistence failed')
        with self.assertRaisesRegex(RuntimeError, 'snapshot persistence failed'):
            self.invoke()
        self.assertIn(('stop', 2), self.events)
        self.capture.assert_called_once()
        self.persist.assert_called_once()
        self.assertFalse((self.run_dir / 'checkpoint.json').exists())
        self.assertNotIn('awaiting_validation', self.phases())
        self.assertIn('inspection_stopped', self.phases())

    def test_capture_receipt_write_failure_keeps_fence_and_incomplete_turn(self):
        original = sandbox_turn.atomic_write_json
        def fail_capture(path, value):
            if Path(path).name == 'capture.json':
                raise OSError('simulated durable write failure')
            return original(path, value)
        with patch.object(sandbox_turn, 'atomic_write_json', side_effect=fail_capture):
            with self.assertRaises(OSError):
                self.invoke()
        self.assertIn(('stop', 2), self.events)
        self.assertNotIn('awaiting_validation', self.phases())
        self.assertTrue((self.root/'model-turn-fences/machine.json').is_file())
        self.assertFalse((self.run_dir/'checkpoint.json').exists())

    def test_stop_during_capture_prevents_persistence_after_lease_exit(self):
        def capture_and_stop(repo, snapshot):
            bundle = self.capture_snapshot(repo, snapshot)
            self.runtime.stop_path.touch()
            return bundle
        self.capture.side_effect = capture_and_stop
        with self.assertRaisesRegex(RuntimeError, 'STOP'):
            self.invoke()
        self.assertIn(('stop', 2), self.events)
        self.persist.assert_not_called()
        self.assertFalse((self.run_dir / 'checkpoint.json').exists())
        self.assertNotIn('awaiting_validation', self.phases())

    def test_nonzero_exit_held_without_inspection_or_retry(self):
        self.execute.side_effect = None
        self.execute.return_value = subprocess.CompletedProcess([], 2), self.export
        result = self.invoke()
        self.assertEqual(result['phase'], 'held')
        self.assertEqual(self.execute.call_count, 1)
        self.assertEqual(self.runtime.count, 1)
        self.read.assert_not_called()

    def test_existing_run_directory_refuses_retry(self):
        self.run_dir.mkdir()
        with self.assertRaises((ValueError, RuntimeError, FileExistsError)):
            self.invoke()
        self.prepare.assert_not_called()

    def test_missing_checkpoint_cannot_reach_validation(self):
        self.read.side_effect = None
        self.read.return_value = {}
        with self.assertRaisesRegex(RuntimeError, 'summary missing'):
            self.invoke()
        self.assertIn(('stop', 2), self.events)
        self.assertNotIn('awaiting_validation', self.phases())

    def test_ownership_failure_cannot_reach_validation(self):
        self.owned.side_effect = RuntimeError('Outside ownership')
        with self.assertRaisesRegex(RuntimeError, 'Outside ownership'):
            self.invoke()
        self.assertIn(('stop', 2), self.events)
        self.fingerprints.assert_not_called()
        self.assertNotIn('awaiting_validation', self.phases())

    def test_coordinator_decision_stored_as_unvalidated_evidence(self):
        patches = {'d' * 40: 'candidate patch'}
        result = self.invoke(role='coordinator', candidate_patches=patches)
        self.assertFalse(result['validation_passed'])
        self.assertFalse(result['committed'])
        self.assertEqual(self.prepare.call_args.kwargs['candidate_patches'], patches)
        checkpoint = json.loads((self.run_dir / 'checkpoint.json').read_text())
        self.assertEqual(checkpoint['decision'], {'accept': []})

    def test_stop_appearing_during_admission_prevents_model(self):
        calls = []
        def admit(*args, **kwargs):
            calls.append(True)
            if kwargs['stage'] == 'before_model':
                self.runtime.stop_path.touch()
        self.admission.side_effect = admit
        with self.assertRaisesRegex(RuntimeError, 'STOP'):
            self.invoke()
        self.execute.assert_not_called()
        self.assertIn(('stop', 1), self.events)

    def test_non_swe_model_evidence_rejected_before_inspection(self):
        self.export['steps'][0]['model_name'] = 'other-model'
        with self.assertRaisesRegex(RuntimeError, 'non-SWE-2'):
            self.invoke()
        self.assertEqual(self.runtime.count, 1)
        self.read.assert_not_called()
        self.assertNotIn('awaiting_validation', self.phases())


if __name__ == '__main__':
    unittest.main()
