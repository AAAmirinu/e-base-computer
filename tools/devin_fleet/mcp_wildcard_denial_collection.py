"""Outer receipt validation for a non-accepting wildcard diagnostic.

No execution/network entry point. The guest collector must first bind exact
profile inputs and export/audit bytes to the stopped attempt.
"""
from mcp_probe_lifecycle import _collection

COUNTERS = {'tool_call_count': 256, 'observation_count': 4096, 'audit_call_count': 64}
FLAGS = frozenset(('exact_requests', 'linked_results', 'sequence_verified',
    'listed_schema_verified', 'strict_refusal_prefix_observed', 'fixed_target_refusal_observed', 'execution_marker_observed',
    'exact_model_verified', 'audit_nonce_verified', 'discovery_sequence_observed',
    'consistent', 'matched_rule_verified', 'permission_denial_accepted',
    'passed', 'production_admitted'))
NEVER_ACCEPT = ('matched_rule_verified', 'permission_denial_accepted', 'passed', 'production_admitted')


def collection(value, **binding):
    if type(value) is not dict or set(value) != {'binding', 'wildcard'}:
        raise ValueError('Bound wildcard collection required')
    verified = _collection(value['binding'], **binding)
    candidate = value['wildcard']
    if (type(candidate) is not dict or set(candidate) != set(COUNTERS) | FLAGS
            or any(type(candidate[k]) is not int or not 0 <= candidate[k] <= cap
                   for k, cap in COUNTERS.items())
            or any(type(candidate[k]) is not bool for k in FLAGS)
            or any(candidate[k] is not False for k in NEVER_ACCEPT)
            or candidate['tool_call_count'] != verified['tool_call_count']
            or candidate['execution_marker_observed'] != verified['execution_marker_seen']
            or candidate['exact_model_verified'] != verified['exact_model_verified']):
        raise ValueError('Finite non-accepting wildcard candidate required')
    expected = (candidate['tool_call_count'] == candidate['observation_count'] == 2
        and all(candidate[k] for k in ('exact_requests', 'linked_results', 'sequence_verified',
            'listed_schema_verified', 'exact_model_verified',
            'audit_nonce_verified', 'discovery_sequence_observed'))
        and (candidate['strict_refusal_prefix_observed'] or candidate['fixed_target_refusal_observed'])
        and not candidate['execution_marker_observed'] and candidate['audit_call_count'] == 0)
    if candidate['consistent'] != expected:
        raise ValueError('Inconsistent wildcard candidate')
    return dict(binding=verified, wildcard=dict(candidate))
