"""Fixed-vocabulary projection of one linked fixture result, never acceptance."""
import re
from mcp_result_summary import summarize as counters, TARGETS

WORDS = frozenset(('tool call execution execute command permission permissions denied rejected '
    'error user by the was has been is not allowed blocked policy for to this due configuration '
    'in normal mode approval required request access cannot because with current settings '
    'explicitly rule rules ask allow deny failed failure server unavailable unknown found '
    'disabled cancelled canceled mcp echo fleet probe on chose choose grant granted '
    'requested requesting rejected declined decided refused '
    'connect reconnect connection closed unexpected eof transport retry retries attempts exhausted '
    'lost disconnected establish reach timed timeout out process exited broken pipe '
    'invalid json response output protocol exception valueerror runtimeerror numeric integer '
    'string id bounded unicode encoding traceback parse parsing received receiving send sending '
    'channel stream eof io transporterror internal initialization initialize startup terminated '
    'termination connectionerror client session closed unexpectedly deserialize deserialization '
    'decode decoding malformed message rpc errorcode cause reason deadline exceeded').split())
TOKENS = WORDS | frozenset((':', '.', '(', ')', '[', ']', '_', '-', "'", '"', '`'))
APPROVAL_REQUIRED = ("Permission to call MCP tool 'echo' on server 'fleet-probe' was denied. "
                     'The user needs to approve access for this MCP server.')


def validate(value):
    if (type(value) is not dict or set(value) != {'linked_result', 'tokens', 'truncated','server_approval_required_exact'}
            or type(value['server_approval_required_exact']) is not bool
            or type(value['linked_result']) is not bool or type(value['truncated']) is not bool
            or type(value['tokens']) is not list or len(value['tokens']) > 80
            or any(type(v) is not str or v not in TOKENS for v in value['tokens'])
            or (not value['linked_result'] and (value['tokens'] or value['truncated'] or value['server_approval_required_exact']))
            or (value['server_approval_required_exact'] and value['truncated'])):
        raise ValueError('Fixed refusal template required')
    return value


def summarize(payload, audit_raw, nonce):
    counters(payload, audit_raw, nonce)  # Full bounded structural validation first.
    calls = [(i,c) for i,s in enumerate(payload['steps']) for c in s.get('tool_calls', [])
             if c['function_name'] == 'mcp_call_tool' and c['arguments'] in TARGETS]
    selected = []
    if len(calls) == 1:
        index, call = calls[0]
        selected = [r['content'] for i,s in enumerate(payload['steps']) if i >= index
            for r in (s.get('observation') or {}).get('results', [])
            if r.get('source_call_id') == call['tool_call_id']]
    if len(selected) != 1:
        return validate(dict(linked_result=False, tokens=[], truncated=False,server_approval_required_exact=False))
    content = selected[0]
    raw = re.findall(r'[a-zA-Z]+|[^\s\w]', content[:1024].lower())
    tokens = [word if word in TOKENS else '_' for word in raw[:80]]
    return validate(dict(linked_result=True,tokens=tokens,truncated=len(content)>1024 or len(raw)>80,
                         server_approval_required_exact=content==APPROVAL_REQUIRED))
