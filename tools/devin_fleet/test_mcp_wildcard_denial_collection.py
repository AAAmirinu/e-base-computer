from copy import deepcopy
from hashlib import sha256
import unittest
from unittest.mock import patch
import mcp_wildcard_denial_collection as outer
from mcp_wildcard_denial_evidence import summarize
from test_mcp_wildcard_denial_evidence import sequence, audit, NONCE


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.bound = {'tool_call_count': 2, 'exact_model_verified': True, 'execution_marker_seen': False}
        self.candidate = summarize(sequence(), audit(), NONCE)

    def collect(self, candidate):
        return outer.collection({'binding': self.bound, 'wildcard': candidate},
            preflight={'fixed': True}, admission_raw=b'admission', stop_raw=b'stop', inspection='lease')

    def test_binding_forwarded_and_candidate_never_accepted(self):
        with patch.object(outer, '_collection', return_value=self.bound) as verify:
            result = self.collect(self.candidate)
        verify.assert_called_once_with(self.bound, preflight={'fixed': True},
            admission_raw=b'admission', stop_raw=b'stop', inspection='lease')
        self.assertTrue(result['wildcard']['consistent'])
        for key in outer.NEVER_ACCEPT: self.assertFalse(result['wildcard'][key])
        self.assertIsNot(result['wildcard'], self.candidate)

    def test_stop_binding_failure_propagates(self):
        with patch.object(outer, '_collection', side_effect=ValueError('stop mismatch')):
            with self.assertRaisesRegex(ValueError, 'stop mismatch'): self.collect(self.candidate)

    def test_execution_marker_disagreement_rejected_in_both_directions(self):
        for observed in (False, True):
            bound = dict(self.bound, execution_marker_seen=not observed)
            candidate = dict(self.candidate, execution_marker_observed=observed, consistent=not observed)
            with patch.object(outer, '_collection', return_value=bound):
                with self.assertRaises(ValueError): self.collect(candidate)

    def test_tampered_candidates_refused(self):
        changes = [{k: True} for k in outer.NEVER_ACCEPT]
        changes += [{'tool_call_count': True}, {'tool_call_count': 1}, {'extra': False},
            {'exact_model_verified': False}, {'consistent': False}, {'audit_call_count': 1},
            {'sequence_verified': False}, {'observation_count': 3}, {'execution_marker_observed': True}]
        for change in changes:
            with self.subTest(change=change), patch.object(outer, '_collection', return_value=self.bound):
                candidate = dict(self.candidate, **change)
                with self.assertRaises(ValueError): self.collect(candidate)

    def test_honest_inconclusive_candidate_retained(self):
        candidate = dict(self.candidate, strict_refusal_prefix_observed=False, consistent=False)
        with patch.object(outer, '_collection', return_value=self.bound):
            self.assertFalse(self.collect(candidate)['wildcard']['consistent'])

    def test_outer_shape_refused_before_binding(self):
        with patch.object(outer, '_collection') as verify:
            for value in ({}, {'binding': self.bound, 'wildcard': self.candidate, 'extra': 1}):
                with self.assertRaises(ValueError): outer.collection(value)
            verify.assert_not_called()

    def test_real_binding_verifier_rejects_changed_stop_and_lease(self):
        flags = ('expected_call_observed', 'discovery_verified', 'exact_model_verified',
            'linked_denial_observed', 'execution_marker_seen', 'production_admitted',
            'permission_denial_observed', 'passed', 'evidence_bound',
            'live_execution_verified', 'inspection_vm_stopped')
        bound = {k: False for k in flags}
        bound.update({k: 'a'*64 for k in ('audit_sha256', 'export_sha256',
            'supervision_sha256', 'session_sha256', 'stop_receipt_sha256',
            'launch_sha256', 'process_result_sha256')})
        bound.update(tool_call_count=2, exact_model_verified=True, evidence_bound=True,
            attempt_nonce=NONCE, inspection_lease_id='inspection',
            supervision_sha256=sha256(b'admission').hexdigest(),
            stop_receipt_sha256=sha256(b'stop').hexdigest())
        value = {'binding': bound, 'wildcard': self.candidate}
        args = dict(preflight={'nonce': NONCE}, admission_raw=b'admission',
                    stop_raw=b'stop', inspection='inspection')
        self.assertTrue(outer.collection(value, **args)['wildcard']['consistent'])
        for change in ({'stop_raw': b'changed'}, {'admission_raw': b'changed'},
                       {'inspection': 'other'}, {'preflight': {'nonce': 'b'*32}}):
            with self.subTest(change=change):
                with self.assertRaises(ValueError): outer.collection(value, **dict(args, **change))


if __name__ == '__main__': unittest.main()
