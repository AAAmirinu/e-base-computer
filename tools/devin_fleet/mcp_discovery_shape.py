"""Finite shape diagnostics only; never asserts discovery or acceptance."""
import json
import math

KNOWN=('tools','result','content','name','inputSchema','input_schema','parameters','server','server_name')
FLAGS=('exact_list_call','linked_result','json_valid','json_object','json_list',
       'tools_array','echo_name_present','empty_object_schema_present','json_fence','markdown_prefix')+tuple('has_'+key for key in KNOWN)
COUNTERS={'content_length':65536,'tool_element_count':256}
FLAGS+=('grouped_fixed_server','grouped_echo_schema')
COUNTERS.update(grouped_tool_count=256,grouped_extra_group_fields=256,grouped_extra_tool_fields=256)
METADATA=('status','server_status','description','server_description','tool_count','total_tools','error','connected','server_id',
          'resources','resource_templates','resourceTemplates','prompts','errors','disabled_tools','unsupported_tools')
FLAGS+=tuple('group_has_'+key for key in METADATA)+('group_extra_null','group_extra_empty_string','group_extra_true',
    'group_extra_false','group_extra_one','group_extra_connected','group_extra_success','group_extra_empty_list')
COUNTERS.update(group_unknown_metadata_count=256)


def validate(value):
    if (type(value) is not dict or set(value)!=set(FLAGS)|set(COUNTERS)
            or any(type(value[key]) is not bool for key in FLAGS)
            or any(type(value[key]) is not int or not 0<=value[key]<=cap for key,cap in COUNTERS.items())):
        raise ValueError('Invalid finite discovery shape')
    return value


def _pairs(items):
    result={}
    for key,value in items:
        if key in result:raise ValueError('Duplicate JSON key')
        result[key]=value
    return result


def _constant(value):raise ValueError('Nonfinite JSON refused')


def _decode(content):
    depth=0;quoted=False;escaped=False
    for char in content:
        if quoted:
            if escaped:escaped=False
            elif char=='\\':escaped=True
            elif char=='"':quoted=False
        elif char=='"':quoted=True
        elif char in '[{':
            depth+=1
            if depth>64:raise ValueError('JSON depth exceeded')
        elif char in ']}':depth-=1
    try:return True,json.loads(content,object_pairs_hook=_pairs,parse_constant=_constant)
    except json.JSONDecodeError:return False,None
    except RecursionError:raise ValueError('JSON depth exceeded') from None


def summarize(payload):
    if type(payload) is not dict:raise ValueError('Export object required')
    try: raw=json.dumps(payload,allow_nan=False)
    except (TypeError,ValueError,RecursionError):raise ValueError('Invalid bounded export') from None
    if len(raw)>1048576:raise ValueError('Export size exceeded')
    steps=payload.get('steps')
    if type(steps) is not list or not 1<=len(steps)<=256:raise ValueError('Bounded steps required')
    calls=[];results=[]
    for index,step in enumerate(steps):
        if type(step) is not dict or step.get('source') not in ('agent','tool','user','system'):
            raise ValueError('Invalid step')
        if step.get('function_call'):raise ValueError('Legacy call refused')
        items=step.get('tool_calls',[])
        if type(items) is not list or len(items)>16 or (items and step['source']!='agent'):
            raise ValueError('Invalid calls')
        for item in items:
            if (type(item) is not dict or type(item.get('function_name')) is not str
                    or not 1<=len(item['function_name'])<=512 or type(item.get('arguments')) is not dict
                    or type(item.get('tool_call_id')) is not str or not 1<=len(item['tool_call_id'])<=128):
                raise ValueError('Invalid call')
            calls.append((index,item))
        observation=step.get('observation')
        if observation is None:continue
        if type(observation) is not dict or step['source'] not in ('agent','tool'):
            raise ValueError('Invalid observation')
        items=observation.get('results')
        if type(items) is not list or len(items)>16:raise ValueError('Invalid results')
        for item in items:
            if (type(item) is not dict or type(item.get('source_call_id')) is not str
                    or not 1<=len(item['source_call_id'])<=128 or type(item.get('content')) is not str
                    or len(item['content'])>65536):raise ValueError('Invalid result')
            results.append((index,item))
    output={key:False for key in FLAGS};output.update({key:0 for key in COUNTERS})
    output['exact_list_call']=(len(calls)==1 and calls[0][1]['function_name']=='mcp_list_tools'
        and calls[0][1]['arguments'] in ({'server_name':'fleet-probe'},{'server':'fleet-probe'}))
    output['linked_result']=bool(output['exact_list_call'] and len(results)==1
        and results[0][0]>=calls[0][0] and results[0][1]['source_call_id']==calls[0][1]['tool_call_id'])
    if not output['linked_result']:return validate(output)
    content=results[0][1]['content'];text=content.lstrip()
    output.update(content_length=len(content),json_fence=text.lower().startswith('```json'),
                  markdown_prefix=text.startswith(('```','#','- ','* ','> ','|')))
    valid,value=_decode(content)
    output.update(json_valid=valid,json_object=valid and type(value) is dict,json_list=valid and type(value) is list)
    if not valid:return validate(output)
    pending=[value]
    while pending:
        node=pending.pop()
        if type(node) is dict:
            for key in KNOWN:output['has_'+key]|=key in node
            pending.extend(node.values())
        elif type(node) is list:pending.extend(node)
        elif type(node) is float and not math.isfinite(node):raise ValueError('Nonfinite JSON refused')
    elements=value if type(value) is list else value.get('tools') if type(value) is dict else None
    if type(elements) is list:
        if len(elements)>256:raise ValueError('Tool array limit')
        output.update(tools_array=True,tool_element_count=len(elements))
        for item in elements:
            if type(item) is not dict:continue
            output['echo_name_present']|=item.get('name')=='echo'
            for key in ('inputSchema','input_schema','parameters'):
                schema=item.get(key)
                output['empty_object_schema_present']|=(type(schema) is dict
                    and set(schema)=={'type','properties','additionalProperties'} and schema['type']=='object'
                    and type(schema['properties']) is dict and not schema['properties']
                    and schema['additionalProperties'] is False)
    if type(value) is list and len(value)==1 and type(value[0]) is dict:
        group=value[0]
        output['grouped_fixed_server']=group.get('server_name')=='fleet-probe'
        output['grouped_extra_group_fields']=len(set(group)-{'server_name','tools'})
        extras=set(group)-{'server_name','tools'}
        output['group_unknown_metadata_count']=len(extras-set(METADATA))
        for key in METADATA:output['group_has_'+key]=key in group
        if len(extras)==1:
            metadata=group[next(iter(extras))]
            output.update(group_extra_null=metadata is None,
                group_extra_empty_string=type(metadata) is str and metadata=='',
                group_extra_true=metadata is True,group_extra_false=metadata is False,
                group_extra_one=type(metadata) is int and metadata==1,
                group_extra_connected=metadata=='connected',group_extra_success=metadata=='success',
                group_extra_empty_list=type(metadata) is list and not metadata)
        tools=group.get('tools')
        if type(tools) is list:
            if len(tools)>256:raise ValueError('Grouped tool bound')
            output['grouped_tool_count']=len(tools)
            if len(tools)==1 and type(tools[0]) is dict:
                tool=tools[0];schema=tool.get('inputSchema')
                output['grouped_extra_tool_fields']=len(set(tool)-{'name','description','inputSchema'})
                output['grouped_echo_schema']=(tool.get('name')=='echo' and type(schema) is dict
                    and set(schema)=={'type','properties','additionalProperties'} and schema['type']=='object'
                    and type(schema['properties']) is dict and not schema['properties']
                    and schema['additionalProperties'] is False)
    return validate(output)
