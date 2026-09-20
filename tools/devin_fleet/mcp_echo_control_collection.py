"""Bind positive echo evidence to one stopped attempt; never admit production."""
from mcp_probe_lifecycle import _collection

COUNTERS = {'tool_call_count': 256, 'observation_count': 4096, 'audit_call_count': 64}
FLAGS = frozenset(('exact_requests', 'linked_results', 'sequence_verified',
    'listed_schema_verified', 'execution_marker_observed', 'exact_model_verified',
    'audit_nonce_verified', 'discovery_sequence_observed', 'linked_success_observed',
    'audit_call_after_list', 'consistent', 'matched_rule_verified',
    'permission_denial_accepted', 'passed', 'production_admitted'))
NEVER_ACCEPT = ('matched_rule_verified', 'permission_denial_accepted', 'passed', 'production_admitted')


def collection(value, **binding):
    if type(value) is not dict or set(value) != {'binding', 'control'}:
        raise ValueError('Bound echo control collection required')
    verified = _collection(value['binding'], **binding)
    candidate = value['control']
    if (type(candidate) is not dict or set(candidate) != set(COUNTERS) | FLAGS
            or any(type(candidate[k]) is not int or not 0 <= candidate[k] <= cap
                   for k, cap in COUNTERS.items())
            or any(type(candidate[k]) is not bool for k in FLAGS)
            or any(candidate[k] is not False for k in NEVER_ACCEPT)
            or candidate['tool_call_count'] != verified['tool_call_count']
            or candidate['execution_marker_observed'] != verified['execution_marker_seen']
            or candidate['exact_model_verified'] != verified['exact_model_verified']):
        raise ValueError('Finite non-accepting echo control candidate required')
    expected = (candidate['tool_call_count'] == candidate['observation_count'] == 2
        and candidate['audit_call_count'] == 1
        and all(candidate[k] for k in ('exact_requests', 'linked_results', 'sequence_verified',
            'listed_schema_verified', 'execution_marker_observed', 'exact_model_verified',
            'audit_nonce_verified', 'discovery_sequence_observed', 'linked_success_observed',
            'audit_call_after_list')))
    if candidate['consistent'] != expected:
        raise ValueError('Inconsistent echo control candidate')
    return dict(binding=verified, control=dict(candidate))
