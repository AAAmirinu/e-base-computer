"""Offline pipeline sequencing tests; all model/validator/VM adapters mocked."""
from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import sandbox_one_turn as pipeline


class OneTurnTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.cycle = self.root / 'cycle'
        self.registration = dict(production_enabled=True, controller_root=str(self.root),
            migration_epoch='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', roles={'machine': {'id': 'vm'}})
        self.active = False
        self.events = []
        self.runtime = SimpleNamespace(registration=self.registration, stop_path=self.root / 'STOP')
        self.factory = Mock(side_effect=self.runtime_context)
        self.admission = Mock()
        self.validated = dict(dispatch_raw=b'dispatch', stdout_raw=b'stdout',
                              validator_id='validator', image_id='image')
        self.built = dict(build_raw=b'build', import_raw=b'import', bundle=b'bundle')
        self.validate = Mock(side_effect=self.validation)
        self.build = Mock(side_effect=self.building)
        self.model = self.install('run_guest_model_phase', side_effect=self.model_phase)
        self.load = self.install('load_snapshot', return_value=(b'manifest', {'hash': b'blob'}, {'files': []}))
        self.install('load_capture', return_value={'capture': {}})
        self.binding = dict(operation_id='a' * 32)
        self.install('load_turn_binding', return_value=self.binding)
        self.bind = self.install('bind_result', return_value={'outcome': 'test_command_succeeded'})
        self.record = self.install('record_candidate', side_effect=self.recording)

    def install(self, name, **kwargs):
        guard = patch.object(pipeline, name, **kwargs)
        result = guard.start()
        self.addCleanup(guard.stop)
        return result

    @contextmanager
    def runtime_context(self):
        self.assertFalse(self.active)
        self.active = True
        self.events.append('enter')
        try:
            yield self.runtime
        finally:
            self.active = False
            self.events.append('exit')

    def model_phase(self, *args, **kwargs):
        self.assertTrue(self.active)
        self.events.append('model')
        return dict(phase='awaiting_validation', operation_id='a' * 32,
                    snapshot={'manifest_sha256': 'b' * 64})

    def validation(self, *args):
        self.assertFalse(self.active)
        self.events.append('validate')
        return self.validated

    def building(self, *args):
        self.assertFalse(self.active)
        self.events.append('build')
        return self.built

    def recording(self, *args, **kwargs):
        self.assertTrue(self.active)
        self.events.append('record')
        return self.root / 'candidate-review' / ('a' * 32) / 'candidate.json'

    def invoke(self, **overrides):
        args = dict(registration=self.registration, controller_root=self.root, project_root=self.root,
            role='machine', entry={'paths': ['src/**']}, state={}, settings={}, cycle_directory=self.cycle,
            sequence=0, runtime_factory=self.factory, admission=self.admission,
            validate=self.validate, build_and_import=self.build)
        args.update(overrides)
        return pipeline.run_one_turn(**args)

    def journal(self):
        return json.loads((self.cycle / 'cycle.json').read_bytes())

    def test_success_closes_runtime_during_validation_and_build(self):
        result = self.invoke()
        self.assertEqual(self.events, ['enter', 'model', 'exit', 'validate', 'build', 'enter', 'record', 'exit'])
        self.assertEqual(result['phase'], 'pending_review')
        self.assertFalse(result['resume_available'])
        self.assertFalse(result['model_retry_allowed'])
        self.assertFalse(result['published'])
        self.assertEqual(self.record.call_args.kwargs['bundle'], b'bundle')
        self.assertEqual(self.record.call_args.kwargs['manifest_raw'], b'manifest')
        self.assertEqual(self.journal(), result)

    def test_model_failure_skips_all_following_adapters(self):
        self.model.side_effect = RuntimeError('synthetic model failure')
        with self.assertRaises(RuntimeError):
            self.invoke()
        self.validate.assert_not_called()
        self.build.assert_not_called()
        self.record.assert_not_called()
        self.assertFalse(self.active)
        self.assertEqual(self.journal()['phase'], 'held')
        self.assertEqual(self.journal()['interrupted_phase'], 'model_pending')

    def test_model_held_result_skips_validation(self):
        self.model.side_effect = None
        self.model.return_value = {'phase': 'held'}
        with self.assertRaises(RuntimeError):
            self.invoke()
        self.validate.assert_not_called()
        self.build.assert_not_called()

    def test_failed_validation_never_builds_candidate(self):
        self.bind.return_value = {'outcome': 'test_command_failed'}
        with self.assertRaises(RuntimeError):
            self.invoke()
        self.build.assert_not_called()
        self.record.assert_not_called()
        self.assertEqual(self.journal()['interrupted_phase'], 'validation_recorded')
        self.assertTrue((self.cycle / 'validation-result' / 'dispatch.json').is_file())
        self.assertIn('validation_archive', self.journal())

    def test_existing_stop_refuses_before_cycle_creation(self):
        (self.root / 'STOP').write_bytes(b'hold')
        with self.assertRaisesRegex(RuntimeError, 'STOP'):
            self.invoke()
        self.model.assert_not_called()
        self.assertFalse(self.cycle.exists())

    def test_stop_after_validation_prevents_candidate_build(self):
        def stop(*args):
            result = self.validation(*args)
            (self.root / 'STOP').write_bytes(b'hold')
            return result
        self.validate.side_effect = stop
        with self.assertRaisesRegex(RuntimeError, 'STOP'):
            self.invoke()
        self.build.assert_not_called()
        self.assertEqual(self.journal()['phase'], 'held')

    def test_stop_after_build_prevents_review_storage(self):
        def stop(*args):
            result = self.building(*args)
            (self.root / 'STOP').write_bytes(b'hold')
            return result
        self.build.side_effect = stop
        with self.assertRaisesRegex(RuntimeError, 'STOP'):
            self.invoke()
        self.record.assert_not_called()
        self.assertEqual(self.factory.call_count, 1)

    def test_candidate_exception_keeps_hold_without_private_error_text(self):
        self.build.side_effect = RuntimeError('SYNTHETIC_PRIVATE_ERROR')
        with self.assertRaises(RuntimeError):
            self.invoke()
        saved = self.journal()
        self.assertEqual(saved['phase'], 'held')
        self.assertEqual(saved['interrupted_phase'], 'candidate_pending')
        self.assertNotIn('SYNTHETIC_PRIVATE_ERROR', json.dumps(saved))
        self.record.assert_not_called()

    def test_same_cycle_cannot_repeat_model_after_failure(self):
        self.validate.side_effect = RuntimeError('validation unavailable')
        with self.assertRaises(RuntimeError):
            self.invoke()
        self.validate.side_effect = self.validation
        with self.assertRaises(FileExistsError):
            self.invoke()
        self.assertEqual(self.model.call_count, 1)
        self.assertEqual(self.factory.call_count, 1)

    def test_missing_adapters_refused_before_model_or_directory(self):
        for name in ('runtime_factory', 'admission', 'validate', 'build_and_import'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.invoke(**{name: None})
        self.model.assert_not_called()
        self.factory.assert_not_called()
        self.assertFalse(self.cycle.exists())

    def test_boolean_validator_success_not_accepted(self):
        self.validate.side_effect = None
        self.validate.return_value = True
        with self.assertRaises(ValueError):
            self.invoke()
        self.bind.assert_not_called()
        self.build.assert_not_called()

    def test_record_failure_closes_runtime_and_holds_cycle(self):
        self.record.side_effect = OSError('synthetic storage failure')
        with self.assertRaises(OSError):
            self.invoke()
        self.assertFalse(self.active)
        self.assertEqual(self.journal()['phase'], 'held')
        self.assertEqual(self.journal()['interrupted_phase'], 'review_store_pending')


if __name__ == '__main__':
    unittest.main()
