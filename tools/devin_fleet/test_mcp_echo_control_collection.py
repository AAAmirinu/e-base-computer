from hashlib import sha256
import unittest
from unittest.mock import patch
import mcp_echo_control_collection as outer
from mcp_echo_control_evidence import summarize, MARKER
from test_mcp_wildcard_denial_evidence import sequence, audit, NONCE


class CollectionTests(unittest.TestCase):
    def setUp(self):
        data = sequence()
        data['steps'][3]['observation']['results'][0]['content'] = MARKER
        self.candidate = summarize(data, audit(('initialized', 'listed', 'called')), NONCE)
        flags = ('expected_call_observed', 'discovery_verified', 'exact_model_verified',
            'linked_denial_observed', 'execution_marker_seen', 'production_admitted',
            'permission_denial_observed', 'passed', 'evidence_bound',
            'live_execution_verified', 'inspection_vm_stopped')
        self.bound = {k: False for k in flags}
        self.bound.update({k: 'a'*64 for k in ('audit_sha256', 'export_sha256',
            'supervision_sha256', 'session_sha256', 'stop_receipt_sha256',
            'launch_sha256', 'process_result_sha256')})
        self.bound.update(tool_call_count=2, exact_model_verified=True, evidence_bound=True,
            execution_marker_seen=True, attempt_nonce=NONCE, inspection_lease_id='inspection',
            supervision_sha256=sha256(b'admission').hexdigest(),
            stop_receipt_sha256=sha256(b'stop').hexdigest())
        self.args = dict(preflight={'nonce': NONCE}, admission_raw=b'admission',
                         stop_raw=b'stop', inspection='inspection')

    def collect(self, candidate=None, bound=None, **changes):
        return outer.collection({'binding': self.bound if bound is None else bound,
            'control': self.candidate if candidate is None else candidate}, **dict(self.args, **changes))

    def test_real_binding_and_positive_candidate_remain_nonaccepting(self):
        result = self.collect()
        self.assertTrue(result['control']['consistent'])
        self.assertIsNot(result['control'], self.candidate)
        for key in outer.NEVER_ACCEPT: self.assertFalse(result['control'][key])

    def test_real_binding_tampering_rejected(self):
        for change in ({'stop_raw': b'changed'}, {'admission_raw': b'changed'},
                       {'inspection': 'other'}, {'preflight': {'nonce': 'b'*32}}):
            with self.subTest(change=change), self.assertRaises(ValueError): self.collect(**change)
        for change in ({'evidence_bound': False}, {'passed': True}, {'production_admitted': True},
                       {'live_execution_verified': True}, {'export_sha256': 'not-a-hash'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.collect(bound=dict(self.bound, **change))

    def test_candidate_schema_types_bounds_and_acceptance_rejected(self):
        candidates = [dict(self.candidate, extra=False)]
        candidates += [{k: v for k, v in self.candidate.items() if k != 'exact_requests'}]
        for key, cap in outer.COUNTERS.items():
            candidates += [dict(self.candidate, **{key: value}) for value in (True, -1, cap+1, 1.0)]
        candidates += [dict(self.candidate, **{key: 1}) for key in outer.FLAGS]
        candidates += [dict(self.candidate, **{key: True}) for key in outer.NEVER_ACCEPT]
        for candidate in candidates:
            with self.subTest(candidate=candidate), self.assertRaises(ValueError): self.collect(candidate)

    def test_recompute_every_success_requirement(self):
        changes = [{'observation_count': 1}, {'audit_call_count': 0}, {'audit_call_count': 2},
                   {'consistent': False}]
        changes += [{key: False} for key in ('exact_requests', 'linked_results', 'sequence_verified',
            'listed_schema_verified', 'execution_marker_observed', 'exact_model_verified',
            'audit_nonce_verified', 'discovery_sequence_observed', 'linked_success_observed',
            'audit_call_after_list')]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.collect(dict(self.candidate, **change))

    def test_binding_candidate_agreement_in_both_directions(self):
        for candidate_key, bound_key in (('execution_marker_observed', 'execution_marker_seen'),
                                        ('exact_model_verified', 'exact_model_verified')):
            for observed in (True, False):
                candidate = dict(self.candidate, **{candidate_key: observed, 'consistent': False})
                bound = dict(self.bound, **{bound_key: not observed})
                with self.subTest(key=candidate_key, observed=observed), self.assertRaises(ValueError):
                    self.collect(candidate, bound)
        with self.assertRaises(ValueError): self.collect(bound=dict(self.bound, tool_call_count=1))

    def test_honest_inconclusive_candidate_retained(self):
        candidate = dict(self.candidate, linked_success_observed=False, consistent=False)
        self.assertFalse(self.collect(candidate)['control']['consistent'])

    def test_shape_then_binding_precedes_candidate_validation(self):
        with patch.object(outer, '_collection') as verify:
            for value in ({}, {'binding': self.bound, 'control': self.candidate, 'extra': 1}):
                with self.assertRaises(ValueError): outer.collection(value, **self.args)
            verify.assert_not_called()
        with patch.object(outer, '_collection', side_effect=ValueError('stop mismatch')) as verify:
            with self.assertRaisesRegex(ValueError, 'stop mismatch'): self.collect({})
            verify.assert_called_once_with(self.bound, **self.args)


if __name__ == '__main__': unittest.main()
