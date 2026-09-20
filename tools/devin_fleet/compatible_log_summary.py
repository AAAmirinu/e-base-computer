"""Fixed compatible-attempt time-window hints, never causal attribution."""
START=1789898172
END=1789898352
PATTERNS={
    'fixture_error':rb'Unsupported fixed probe request',
    'fixture_numeric_id_error':rb'Bounded numeric request id required',
    'fixture_compatible_id_error':rb'Bounded string or integer request id required',
    'fixture_protocol_error':rb'Invalid protocol request',
    'fixture_input_limit':rb'Protocol input limit',
    'fixture_audit_error':rb'Audit size limit|Incomplete audit event|Fixed audit event required',
    'traceback':rb'Traceback \(most recent call last\)',
    'broken_pipe':rb'BrokenPipeError|broken pipe',
    'unicode_error':rb'UnicodeEncodeError|UnicodeDecodeError',
    'json_error':rb'JSONDecodeError',
    'value_error':rb'ValueError',
    'connection_closed':rb'connection closed|connection reset|connection refused',
    'connect_failure':rb'failed to connect',
    'process_exit':rb'process[^\n]{0,60}(exited|terminated)|exit code',
    'signal':rb'SIGKILL|SIGTERM|signal 9|signal 15',
    'timeout':rb'timeout|timed out|deadline exceeded',
    'fixture_name':rb'fleet-probe',
}
CONTEXT={
    'invalid_params':rb'-32602',
    'fixture_name':rb'fleet-probe',
    'tool_call':rb'tools/call|mcp_call_tool',
    'resource_list':rb'resources/list',
    'prompt_list':rb'prompts/list',
    'metadata':rb'_meta',
    'source_code':rb'return |def reply|raise ValueError',
}
for _name,_pattern in CONTEXT.items():
    PATTERNS['fixture_error_line_'+_name]=(rb'(?m)^(?=[^\n]{0,2048}Unsupported fixed probe request)'
        rb'(?=[^\n]{0,2048}(?:'+_pattern+rb'))[^\n]{0,2048}')

EVENT_SOURCE=r'''
import json
_text_classify=classify
_event_keys=('event_fixture_error','event_invalid_params','event_tool_call','event_resource_list','event_prompt_list','event_unknown_method','fixture_line_nonjson','fixture_line_invalid_json','fixture_line_json_without_message')
for _key in _event_keys:PATTERNS[_key]=rb'(?!)'
def _pairs(items):
    result={}
    for key,value in items:
        if key in result:raise ValueError('Duplicate key')
        result[key]=value
    return result
def classify(raw):
    result=_text_classify(raw)
    for line in raw.splitlines():
        if b'Unsupported fixed probe request' not in line:continue
        if len(line)>65536 or not line.lstrip().startswith(b'{'):
            result['fixture_line_nonjson']=min(1000,result['fixture_line_nonjson']+1);continue
        try:value=json.loads(line,object_pairs_hook=_pairs)
        except (ValueError,UnicodeError,RecursionError):
            result['fixture_line_invalid_json']=min(1000,result['fixture_line_invalid_json']+1);continue
        nodes=[value] if type(value) is dict else []
        for depth in range(4):
            children=[node[k] for node in list(nodes) for k in ('fields','error','cause','data') if type(node.get(k)) is dict]
            nodes.extend(n for n in children if all(n is not old for old in nodes))
            if len(nodes)>64:break
        if len(nodes)>64:continue
        messages=[node[k] for node in nodes for k in ('message','msg') if type(node.get(k)) is str]
        if not any('Unsupported fixed probe request' in message for message in messages):
            result['fixture_line_json_without_message']=min(1000,result['fixture_line_json_without_message']+1);continue
        flags={'event_fixture_error'}
        if any(type(node.get('code')) is int and node['code']==-32602 for node in nodes):flags.add('event_invalid_params')
        methods=[node['method'] for node in nodes if type(node.get('method')) is str]
        for method in methods:
            flags.add({'tools/call':'event_tool_call','resources/list':'event_resource_list','prompts/list':'event_prompt_list'}.get(method,'event_unknown_method'))
        for key in flags:result[key]=min(1000,result[key]+1)
    return result
'''
# Expose the exact finite wire keys to the outer validator as well.
for _key in ('event_fixture_error','event_invalid_params','event_tool_call','event_resource_list','event_prompt_list','event_unknown_method','fixture_line_nonjson','fixture_line_invalid_json','fixture_line_json_without_message'):
    PATTERNS[_key]=rb'(?!)'

def compose(source):
    if type(source) is not str or not 0<len(source.encode())<=16384:
        raise ValueError('Bounded trusted log reader source required')
    result=source+'\nSTART='+repr(START)+'\nEND='+repr(END)+'\nPATTERNS='+repr(PATTERNS)+'\nREJECTION_CONTEXT={}\n'
    result+=EVENT_SOURCE
    if len(result.encode())>16384:raise ValueError('Composed log reader limit')
    compile(result,'<trusted-compatible-logs>','exec')
    return result
