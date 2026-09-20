"""Positive fixture evidence only; no permission attribution or fleet admission."""
import json
from mcp_discovery_evidence import _pairs, _constant
from mcp_wildcard_denial_evidence import summarize as sequence_summary
from mcp_denial_fixture import MARKER


def _success(content):
    if content == MARKER: return True
    # Whole-export validation has already bounded/checked JSON depth and keys.
    try: value=json.loads(content,object_pairs_hook=_pairs,parse_constant=_constant)
    except json.JSONDecodeError:return False
    expected={'content':[{'type':'text','text':MARKER}],'isError':False}
    return (type(value) is dict and set(value)==set(expected)
            and value['isError'] is False and value['content']==expected['content'])


def summarize(payload,audit_raw,nonce):
    base=sequence_summary(payload,audit_raw,nonce)
    success=False
    if base['exact_requests'] and base['linked_results'] and base['sequence_verified']:
        calls=[c for s in payload['steps'] for c in s.get('tool_calls',[])]
        identity=calls[1]['tool_call_id']
        results=[r for s in payload['steps'] for r in (s.get('observation') or {}).get('results',[])
                 if r['source_call_id']==identity]
        success=len(results)==1 and _success(results[0]['content'])
    # Check actual audit event order too, not merely independent event counts.
    events=[line.partition(':')[2] for line in audit_raw.decode('ascii').splitlines()]
    audit_order=(base['audit_nonce_verified'] and events.count('called')==1
                 and 'listed' in events and events.index('listed')<events.index('called'))
    keys=('tool_call_count','observation_count','exact_requests','linked_results','sequence_verified',
          'listed_schema_verified','execution_marker_observed','exact_model_verified',
          'audit_nonce_verified','audit_call_count','discovery_sequence_observed')
    result={k:base[k] for k in keys}
    consistent=bool(success and audit_order and base['listed_schema_verified']
        and base['exact_model_verified'] and base['discovery_sequence_observed'])
    return dict(result,linked_success_observed=bool(success),audit_call_after_list=bool(audit_order),
        consistent=consistent,matched_rule_verified=False,permission_denial_accepted=False,
        passed=False,production_admitted=False)
