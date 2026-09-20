"""Pure bounded diagnostic counters. Never return export strings or acceptance."""
import json
import re
from mcp_probe_audit import summarize_nonce_audit

TOOL='mcp__fleet-probe__echo'
LIMITS={'step_count':256,'expected_tool_count':4096,'other_mcp_count':4096,
        'other_tool_count':4096,'arguments_empty_count':4096,'observation_count':4096,
        'permission_denial_count':4096,'unknown_tool_count':4096,
        'unavailable_server_count':4096,'other_observation_count':4096,
        'audit_initialization_count':64,'audit_list_count':64,'audit_call_count':64}
FLAGS=('audit_nonce_verified','audit_discovery_sequence_observed')
LIMITS.update(mcp_list_tools_count=4096,mcp_list_servers_count=4096,mcp_call_tool_count=4096,
              observation_policy_words_count=4096)
LIMITS.update(generic_exact_target_count=4096,generic_linked_result_count=4096,
              generic_linked_denied_word_count=4096,generic_linked_policy_word_count=4096)
TARGETS=({'server_name':'fleet-probe','tool_name':'echo','arguments':{}},
         {'server':'fleet-probe','tool':'echo','arguments':{}},
         {'server_name':'fleet-probe','tool_name':'echo','arguments':'{}'})


def validate(value):
    """Validate the complete non-secret wire contract, without coercions."""
    if type(value) is not dict or set(value)!=set(LIMITS)|set(FLAGS):
        raise ValueError('Unexpected diagnostic summary shape')
    if any(type(value[k]) is not int or not 0<=value[k]<=cap for k,cap in LIMITS.items()):
        raise ValueError('Invalid diagnostic counter')
    if any(type(value[k]) is not bool for k in FLAGS):
        raise ValueError('Invalid diagnostic flag')
    calls=sum(value[k] for k in ('expected_tool_count','other_mcp_count','other_tool_count'))
    observations=sum(value[k] for k in ('permission_denial_count','unknown_tool_count',
                                      'unavailable_server_count','other_observation_count'))
    if (not 1<=value['step_count']<=256 or calls>value['step_count']*16
            or value['arguments_empty_count']>calls
            or observations!=value['observation_count'] or observations>value['step_count']*16
            or sum(value[k] for k in ('audit_initialization_count','audit_list_count','audit_call_count'))>64
            or sum(value[k] for k in ('mcp_list_tools_count','mcp_list_servers_count','mcp_call_tool_count'))>value['other_tool_count']
            or value['observation_policy_words_count']>value['observation_count']
            or value['generic_exact_target_count']>value['mcp_call_tool_count']
            or value['generic_linked_result_count']>value['observation_count']
            or value['generic_linked_denied_word_count']>value['generic_linked_result_count']
            or value['generic_linked_policy_word_count']>value['generic_linked_result_count']):
        raise ValueError('Inconsistent diagnostic counters')
    return value


def _string(value,limit):
    return type(value) is str and 0<len(value)<=limit


def summarize(payload,audit_raw,nonce):
    if type(payload) is not dict or type(nonce) is not str or re.fullmatch('[0-9a-f]{32}',nonce) is None:
        raise ValueError('Export and fixed nonce required')
    # Bound even ignored metadata/arguments. Never expose encoder exceptions.
    try:
        encoded=json.dumps(payload,allow_nan=False,ensure_ascii=True)
    except (TypeError,ValueError,RecursionError):
        raise ValueError('Invalid export JSON') from None
    if len(encoded)>1048576:
        raise ValueError('Export size limit')
    steps=payload.get('steps')
    if type(steps) is not list or not 1<=len(steps)<=256:
        raise ValueError('Bounded export steps required')
    result={key:0 for key in LIMITS}
    result.update({key:False for key in FLAGS})
    result['step_count']=len(steps)
    target_ids=set()
    all_ids=set()
    for step in steps:
        if type(step) is not dict or step.get('source') not in ('system','user','agent','tool'):
            raise ValueError('Invalid export step')
        if step.get('function_call'):
            raise ValueError('Unsupported legacy call format')
        calls=step.get('tool_calls',[])
        if type(calls) is not list or len(calls)>16 or (calls and step['source']!='agent'):
            raise ValueError('Invalid export calls')
        for call in calls:
            if (type(call) is not dict or not _string(call.get('function_name'),512)
                    or not _string(call.get('tool_call_id'),128) or type(call.get('arguments')) is not dict):
                raise ValueError('Invalid export call')
            name=call['function_name']
            if call['tool_call_id'] in all_ids: raise ValueError('Duplicate call identity')
            all_ids.add(call['tool_call_id'])
            if name=='mcp_call_tool' and any(call['arguments']==target for target in TARGETS):
                result['generic_exact_target_count']+=1
                target_ids.add(call['tool_call_id'])
            if name in ('mcp_list_tools','mcp_list_servers','mcp_call_tool'):
                result[name+'_count']+=1
            key='expected_tool_count' if name==TOOL else ('other_mcp_count' if name.startswith('mcp__') else 'other_tool_count')
            result[key]+=1
            result['arguments_empty_count']+=int(not call['arguments'])
        observation=step.get('observation')
        if observation is None: continue
        if type(observation) is not dict or step['source'] not in ('agent','tool'):
            raise ValueError('Invalid export observation')
        values=observation.get('results')
        if type(values) is not list or len(values)>16:
            raise ValueError('Invalid observation results')
        for item in values:
            if (type(item) is not dict or type(item.get('content')) is not str or len(item['content'])>65536
                    or ('source_call_id' in item and not _string(item['source_call_id'],128))):
                raise ValueError('Invalid observation result')
            content=item['content'].strip().lower()
            if item.get('source_call_id') in target_ids:
                result['generic_linked_result_count']+=1
                result['generic_linked_denied_word_count']+=int(bool(re.search(r'\b(denied|not allowed|not permitted|blocked)\b',content)))
                result['generic_linked_policy_word_count']+=int(bool(re.search(r'\b(permission|policy)\b',content)))
            if re.search(r'\b(denied|not allowed|not permitted|permission|policy)\b',content):
                result['observation_policy_words_count']+=1
            if content.startswith(('permission denied','tool execution denied','not allowed by permission policy','blocked by permission policy')):
                key='permission_denial_count'
            elif content.startswith(('unknown tool','tool not found','no such tool')):
                key='unknown_tool_count'
            elif content.startswith(('unavailable server','server unavailable','mcp server unavailable','server not found','mcp server not found')):
                key='unavailable_server_count'
            else: key='other_observation_count'
            result[key]+=1
            result['observation_count']+=1
    if type(audit_raw) is not bytes:
        raise ValueError('Bounded audit bytes required')
    if audit_raw:
        try: audit=summarize_nonce_audit(audit_raw,nonce)
        except (ValueError,UnicodeError):
            raise ValueError('Invalid nonce audit') from None
        result.update(audit_initialization_count=audit['initialization_count'],
                      audit_list_count=audit['tool_list_count'],audit_call_count=audit['tool_call_count'],
                      audit_nonce_verified=audit['attempt_nonce_verified'],
                      audit_discovery_sequence_observed=audit['discovery_sequence_observed'])
    return validate(result)
