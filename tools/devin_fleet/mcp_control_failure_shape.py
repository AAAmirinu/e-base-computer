"""Finite linked-response indicators, not causal attribution or acceptance."""
from mcp_result_summary import summarize as counters,TARGETS

KEYS=('unique_linked_result','fixture_error_literal_present','invalid_params_code_present','marker_present')

def validate(value):
    if type(value) is not dict or set(value)!=set(KEYS) or any(type(value[k]) is not bool for k in KEYS):
        raise ValueError('Finite control failure indicators required')
    if not value['unique_linked_result'] and any(value[k] for k in KEYS[1:]):
        raise ValueError('Linked result required')
    return value

def summarize(payload,audit_raw,nonce):
    counters(payload,audit_raw,nonce)
    calls=[(i,c) for i,s in enumerate(payload['steps']) for c in s.get('tool_calls',[])
           if c['function_name']=='mcp_call_tool' and c['arguments'] in TARGETS]
    result=dict.fromkeys(KEYS,False)
    if len(calls)!=1:return validate(result)
    index,call=calls[0]
    linked=[r['content'] for i,s in enumerate(payload['steps']) if i>=index
            for r in (s.get('observation') or {}).get('results',[])
            if r.get('source_call_id')==call['tool_call_id']]
    if len(linked)!=1:return validate(result)
    value=linked[0]
    return validate(dict(unique_linked_result=True,
        fixture_error_literal_present='Unsupported fixed probe request' in value,
        invalid_params_code_present='-32602' in value,
        marker_present='EBASE_MCP_FIXTURE_CALLED' in value))
