"""Synthetic validator result binding; never starts a process or executes source."""
import copy
import hashlib
import json
import unittest

from turn_validation_result import bind_result


class TurnValidationResultTests(unittest.TestCase):
    def setUp(self):
        self.validator = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc'
        self.image = 'sha256:' + 'f' * 64
        self.binding = dict(turn_sha256='a' * 64, capture_sha256='b' * 64,
            operation_id='c' * 32, migration_epoch='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
            sequence=1, role='machine', sandbox_id='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
            manifest_sha256='d' * 64, base='e' * 40)
        operation = '1' * 32
        self.receipt = dict(schema=1, operation=operation, container_id='2' * 64,
            manifest_sha256='d' * 64, image_id=self.image, base='e' * 40,
            container_name='e-base-check-' + operation, phase='complete',
            container_stopped=True, validation_passed=False,
            materialization=dict(manifest_sha256='d' * 64, base='e' * 40),
            boundary=dict(observations_verified=True, full_isolation_accepted=False),
            test=dict(reason='exited', returncode=0, reported_test_count=12, output_sha256='3' * 64),
            test_command_succeeded=True)
        self.envelope = dict(receipt=self.receipt,
                            receipt_path='/tmp/validation-source-' + operation + '.json')
        self.dispatch = dict(schema=1, turn_evidence=copy.deepcopy(self.binding),
            sandbox_id=self.validator, image_id=self.image, manifest_sha256='d' * 64,
            base='e' * 40, validation_vm_stopped=True, validation_passed=False,
            returncode=0, phase='complete')

    def encoded(self):
        stdout = (json.dumps(self.envelope) + '\n').encode()
        dispatch = dict(self.dispatch, stdout_sha256=hashlib.sha256(stdout).hexdigest(),
                        runner_summary=copy.deepcopy(self.envelope))
        return dispatch, stdout

    def invoke(self):
        dispatch, stdout = self.encoded()
        return self.call(dispatch, stdout)

    def call(self, dispatch, stdout):
        return bind_result(self.binding, json.dumps(dispatch).encode(), stdout,
                           validator_id=self.validator, image_id=self.image)

    def test_success_only_requires_review(self):
        result = self.invoke()
        self.assertEqual(result['outcome'], 'test_command_succeeded')
        self.assertTrue(result['review_required'])
        for key in ('production_accepted', 'committed', 'resume_available'):
            self.assertIs(result[key], False)
        self.assertEqual(result['turn_binding'], self.binding)
        self.assertEqual(result['reported_test_count'], 12)

    def test_recorded_derived_result_and_json_format_do_not_change_evidence_digest(self):
        dispatch, stdout = self.encoded()
        first = self.call(dispatch, stdout)
        dispatch['turn_result'] = first
        self.assertEqual(self.call(dispatch, stdout), first)
        formatted = json.dumps(dispatch, sort_keys=True, indent=2).encode()
        self.assertEqual(bind_result(self.binding, formatted, stdout,
                                    validator_id=self.validator, image_id=self.image), first)

    def test_consistent_test_failure_is_review_evidence(self):
        self.receipt['test']['returncode'] = 1
        self.receipt['test_command_succeeded'] = False
        self.dispatch.update(returncode=1, phase='inspection_required')
        result = self.invoke()
        self.assertEqual(result['outcome'], 'test_command_failed')
        self.assertTrue(result['review_required'])
        self.assertFalse(result['resume_available'])

    def test_dispatch_identity_and_stop_mismatches_rejected(self):
        original = copy.deepcopy(self.dispatch)
        for key, value in (('sandbox_id', self.binding['sandbox_id']), ('image_id', 'sha256:' + '0' * 64),
                           ('manifest_sha256', '0' * 64), ('base', '0' * 40),
                           ('validation_vm_stopped', False), ('validation_vm_stopped', 1),
                           ('validation_passed', True), ('schema', True)):
            with self.subTest(key=key, value=value):
                self.dispatch = dict(original, **{key: value})
                with self.assertRaises(ValueError):
                    self.invoke()

    def test_turn_binding_mismatch_rejected(self):
        self.dispatch['turn_evidence']['operation_id'] = '0' * 32
        with self.assertRaises(ValueError):
            self.invoke()

    def test_saved_sequence_type_cannot_alias_integer(self):
        for value in (True, 1.0):
            with self.subTest(value=value):
                self.dispatch['turn_evidence']['sequence'] = value
                with self.assertRaises(ValueError):
                    self.invoke()

    def test_saved_summary_numeric_types_must_match_output(self):
        for key, value in (('returncode', False), ('reported_test_count', 12.0)):
            with self.subTest(key=key):
                dispatch, stdout = self.encoded()
                dispatch['runner_summary']['receipt']['test'][key] = value
                with self.assertRaises(ValueError):
                    self.call(dispatch, stdout)

    def test_stdout_digest_mismatch_rejected(self):
        dispatch, stdout = self.encoded()
        dispatch['stdout_sha256'] = '0' * 64
        with self.assertRaises(ValueError):
            self.call(dispatch, stdout)

    def test_saved_summary_is_not_used_instead_of_actual_output(self):
        dispatch, stdout = self.encoded()
        dispatch['runner_summary']['receipt']['test']['reported_test_count'] = 999
        with self.assertRaises(ValueError):
            self.call(dispatch, stdout)

    def test_runner_identity_and_cleanup_mismatches_rejected(self):
        original = copy.deepcopy(self.receipt)
        for key, value in (('image_id', 'sha256:' + '0' * 64), ('manifest_sha256', '0' * 64),
                           ('container_stopped', False), ('phase', 'running'),
                           ('validation_passed', True)):
            with self.subTest(key=key):
                self.receipt.clear()
                self.receipt.update(copy.deepcopy(original))
                self.receipt[key] = value
                with self.assertRaises(ValueError):
                    self.invoke()

    def test_missing_boundary_evidence_rejected(self):
        for boundary in ({}, {'observations_verified': False, 'full_isolation_accepted': False},
                         {'observations_verified': True, 'full_isolation_accepted': True}):
            with self.subTest(boundary=boundary):
                self.receipt['boundary'] = boundary
                with self.assertRaises(ValueError):
                    self.invoke()

    def test_invalid_execution_fields_rejected(self):
        original = copy.deepcopy(self.receipt['test'])
        for key, value in (('reason', 'timeout'), ('returncode', False),
                           ('reported_test_count', True), ('reported_test_count', 0),
                           ('reported_test_count', 12.0), ('output_sha256', 'bad')):
            with self.subTest(key=key, value=value):
                self.receipt['test'] = dict(original, **{key: value})
                with self.assertRaises(ValueError):
                    self.invoke()

    def test_inconsistent_success_signals_rejected(self):
        for test_rc, succeeded, outer_rc, phase in (
                (1, True, 0, 'complete'), (0, False, 0, 'complete'),
                (0, True, 1, 'inspection_required'), (1, False, 0, 'complete'),
                (0, True, 0, 'inspection_required')):
            with self.subTest(test_rc=test_rc, succeeded=succeeded, outer_rc=outer_rc, phase=phase):
                self.receipt['test']['returncode'] = test_rc
                self.receipt['test_command_succeeded'] = succeeded
                self.dispatch.update(returncode=outer_rc, phase=phase)
                with self.assertRaises(ValueError):
                    self.invoke()

    def test_validator_must_differ_from_authenticated_vm(self):
        self.validator = self.binding['sandbox_id']
        with self.assertRaises(ValueError):
            self.invoke()

    def test_partial_duplicate_or_ambiguous_output_rejected(self):
        dispatch, stdout = self.encoded()
        for raw in (b'{', stdout + stdout, stdout.replace(b'"receipt": {', b'"receipt": {"schema":2,', 1)):
            with self.subTest(raw_prefix=raw[:20]):
                dispatch['stdout_sha256'] = hashlib.sha256(raw).hexdigest()
                with self.assertRaises(ValueError):
                    self.call(dispatch, raw)

    def test_duplicate_dispatch_keys_rejected(self):
        dispatch, stdout = self.encoded()
        raw = b'{"schema":2,' + json.dumps(dispatch).encode()[1:]
        with self.assertRaises(ValueError):
            bind_result(self.binding, raw, stdout, validator_id=self.validator, image_id=self.image)


if __name__ == '__main__':
    unittest.main()
