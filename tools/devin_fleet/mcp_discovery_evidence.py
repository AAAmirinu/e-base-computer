"""Pure discovery candidate evidence. No execution, binding, or acceptance."""
import json
import re
from mcp_probe_audit import summarize_nonce_audit

MODELS=('swe-2-high','SWE-2 High')


def _pairs(items):
    value={}
    for key,item in items:
        if key in value: raise ValueError('Duplicate JSON key')
        value[key]=item
    return value


def _constant(value):
    raise ValueError('Nonfinite JSON refused')


def _listing(content):
    # Ordinary prose/Markdown is unconfirmed, never evidence from agent text.
    # Bound nesting ourselves: decoder recursion limits differ across runtimes.
    depth=0;quoted=False;escaped=False
    for char in content:
        if quoted:
            if escaped:escaped=False
            elif char=='\\':escaped=True
            elif char=='"':quoted=False
        elif char=='"':quoted=True
        elif char in '[{':
            depth+=1
            if depth>64:raise ValueError('Observation JSON depth exceeded')
        elif char in ']}':depth-=1
    try: value=json.loads(content,object_pairs_hook=_pairs,parse_constant=_constant)
    except json.JSONDecodeError: return False
    except RecursionError: raise ValueError('Observation JSON depth exceeded') from None
    # Observed CLI envelope v2: one fixed server, no resources. Keep the
    # original object form independent; unknown metadata is never ignored.
    if type(value) is list:
        if (len(value)!=1 or type(value[0]) is not dict
                or set(value[0])!={'server_name','tools','resources'}
                or value[0]['server_name']!='fleet-probe'
                or type(value[0]['resources']) is not list or value[0]['resources']):
            return False
        value={'tools':value[0]['tools']}
    if type(value) is not dict or set(value)!={'tools'} or type(value['tools']) is not list or len(value['tools'])!=1:
        return False
    tool=value['tools'][0]
    if (type(tool) is not dict or not {'name','inputSchema'}<=set(tool)
            or set(tool)-{'name','inputSchema','description'} or tool['name']!='echo'
            or ('description' in tool and type(tool['description']) is not str)):
        return False
    schema=tool['inputSchema']
    return (type(schema) is dict and set(schema)=={'type','properties','additionalProperties'}
            and schema['type']=='object' and type(schema['properties']) is dict
            and not schema['properties'] and schema['additionalProperties'] is False)


def summarize(payload,audit_raw,nonce):
    if type(payload) is not dict or type(nonce) is not str or re.fullmatch('[0-9a-f]{32}',nonce) is None:
        raise ValueError('Export and fixed nonce required')
    try: encoded=json.dumps(payload,ensure_ascii=True,allow_nan=False)
    except (ValueError,TypeError,RecursionError): raise ValueError('Invalid export JSON') from None
    if len(encoded)>1048576: raise ValueError('Bounded export required')
    steps=payload.get('steps')
    if type(steps) is not list or not 1<=len(steps)<=256:
        raise ValueError('Bounded export steps required')
    calls=[];call_steps=[];results=[];agents=[]
    for step_index,step in enumerate(steps):
        if type(step) is not dict or step.get('source') not in ('system','user','agent','tool'):
            raise ValueError('Unknown export step')
        if step.get('function_call'): raise ValueError('Unsupported legacy call')
        items=step.get('tool_calls',[])
        if type(items) is not list or len(items)>16 or (items and step['source']!='agent'):
            raise ValueError('Invalid tool calls')
        for item in items:
            if (type(item) is not dict or type(item.get('function_name')) is not str
                    or not 1<=len(item['function_name'])<=512 or type(item.get('arguments')) is not dict
                    or type(item.get('tool_call_id')) is not str or not 1<=len(item['tool_call_id'])<=128):
                raise ValueError('Invalid tool call')
        calls.extend(items)
        call_steps.extend([step_index]*len(items))
        if step['source']=='agent':agents.append(step)
        observation=step.get('observation')
        if observation is not None:
            if type(observation) is not dict or step['source'] not in ('tool','agent'):
                raise ValueError('Invalid observation')
            values=observation.get('results')
            if type(values) is not list or len(values)>16:raise ValueError('Invalid observation results')
            for item in values:
                if (type(item) is not dict or type(item.get('content')) is not str
                        or len(item['content'])>65536
                        or type(item.get('source_call_id')) is not str or not 1<=len(item['source_call_id'])<=128):
                    raise ValueError('Invalid observation result')
                # Reject ambiguous/nonfinite JSON even if the result is unlinked.
                recognized=_listing(item['content'])
                results.append((item['source_call_id'],recognized,step_index))
    ids=[call['tool_call_id'] for call in calls]
    unique=len(set(ids))==len(ids)
    exact=(len(calls)==1 and unique and calls[0]['function_name']=='mcp_list_tools'
           and calls[0]['arguments'] in ({'server_name':'fleet-probe'},{'server':'fleet-probe'}))
    linked=[recognized for identity,recognized,index in results
            if exact and identity==ids[0] and index>=call_steps[0]]
    listed=len(results)==1 and len(linked)==1 and linked[0]
    model=bool(agents) and all(step.get('model_name') in MODELS for step in agents)
    if type(audit_raw) is not bytes:raise ValueError('Audit bytes required')
    if audit_raw:
        try:audit=summarize_nonce_audit(audit_raw,nonce)
        except (ValueError,UnicodeError):raise ValueError('Invalid nonce audit') from None
    else:
        audit=dict(initialization_count=0,tool_list_count=0,tool_call_count=0,
                   discovery_sequence_observed=False,attempt_nonce_verified=False)
    discovery=(audit['attempt_nonce_verified'] and audit['initialization_count']>=1
               and audit['tool_list_count']>=1 and audit['discovery_sequence_observed'])
    return dict(tool_call_count=len(calls),observation_count=len(results),linked_result_count=len(linked),
                call_ids_unique=unique,expected_list_call_observed=exact,listed_schema_verified=bool(listed),
                exact_model_verified=model,audit_initialization_count=audit['initialization_count'],
                audit_list_count=audit['tool_list_count'],audit_call_count=audit['tool_call_count'],
                audit_nonce_verified=audit['attempt_nonce_verified'],discovery_sequence_observed=bool(discovery),
                consistent=bool(exact and listed and model and discovery and audit['tool_call_count']==0),
                passed=False,production_admitted=False)
