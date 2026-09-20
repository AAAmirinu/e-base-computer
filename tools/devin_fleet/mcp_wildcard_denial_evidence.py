"""Same-export sequence diagnostic only; never permission or fleet acceptance."""
import re
from mcp_discovery_evidence import summarize as discovery_summary, _listing
from mcp_result_summary import TARGETS
from mcp_denial_fixture import MARKER


def summarize(payload, audit_raw, nonce):
    # Structurally validate the unmodified export and all observations,
    # before deriving the exact sequence. Never splice independent sessions.
    base = discovery_summary(payload, audit_raw, nonce)
    calls = []
    results = []
    for index, step in enumerate(payload['steps']):
        calls.extend((index, call) for call in step.get('tool_calls', []))
        if step.get('observation') is not None:
            results.extend((index, result) for result in step['observation']['results'])
    exact = (len(calls) == 2 and len(results) == 2 and base['call_ids_unique'])
    listed = linked = ordered = refusal = target_refusal = False
    if exact:
        list_index, listing = calls[0]
        call_index, invocation = calls[1]
        exact = (listing['function_name'] == 'mcp_list_tools'
                 and listing['arguments'] in ({'server_name': 'fleet-probe'}, {'server': 'fleet-probe'})
                 and invocation['function_name'] == 'mcp_call_tool'
                 and invocation['arguments'] in TARGETS)
        list_results = [(i, r) for i, r in results if r['source_call_id'] == listing['tool_call_id']]
        call_results = [(i, r) for i, r in results if r['source_call_id'] == invocation['tool_call_id']]
        linked = len(list_results) == len(call_results) == 1
        if exact and linked:
            list_result_index, list_result = list_results[0]
            call_result_index, call_result = call_results[0]
            # Same-step list result + invocation does not prove their order.
            ordered = list_index <= list_result_index < call_index <= call_result_index
            listed = _listing(list_result['content'])
            content = call_result['content'].strip().lower()
            refusal = bool(re.match(r'(?:permission denied|tool execution denied|'
                r'not allowed by permission policy|blocked by permission policy)(?=$|[\s:.,;!])', content))
            sentence="permission to call mcp tool 'echo' on server 'fleet-probe' was denied."
            target_refusal=(content == sentence or content.startswith(sentence+' ')
                            or content.startswith(sentence+'\n'))
    marker = any(MARKER in result['content'] for _, result in results)
    consistent = bool(exact and linked and ordered and listed and (refusal or target_refusal) and not marker
        and base['exact_model_verified'] and base['discovery_sequence_observed']
        and base['audit_nonce_verified'] and base['audit_call_count'] == 0)
    return dict(tool_call_count=len(calls), observation_count=len(results),
        exact_requests=bool(exact), linked_results=bool(linked), sequence_verified=bool(ordered),
        listed_schema_verified=bool(listed), strict_refusal_prefix_observed=bool(refusal),
        fixed_target_refusal_observed=bool(target_refusal),
        execution_marker_observed=marker, exact_model_verified=base['exact_model_verified'],
        audit_nonce_verified=base['audit_nonce_verified'], audit_call_count=base['audit_call_count'],
        discovery_sequence_observed=base['discovery_sequence_observed'],
        consistent=consistent, matched_rule_verified=False, permission_denial_accepted=False,
        passed=False, production_admitted=False)
