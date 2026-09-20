"""Fixed current-workdir CLI history shape; not account-wide inventory proof."""
import json
import re
import hashlib

FIELDS=('sessions','data','items','id','session_id','next_cursor','has_more')


def read_empty_workdir_inventory(work,*,timeout=10):
    """Trusted supervisor helper for a fresh reserved workdir, not global history.

    Caller must verify config/VM/network before even this non-model CLI command.
    No unknown or failed response is treated as an empty history.
    """
    from mcp_probe_catalog import _capture,CLI
    from validation_dispatch_receipt import _pairs
    if type(work) is not str or re.fullmatch('/tmp/e-base-mcp-probe-[a-z0-9_]{8}',work) is None:
        raise ValueError('Exact reserved workdir required')
    raw,rc=_capture([CLI,'--config',work+'/config.json','list','--format','json'],work,timeout=timeout)
    if type(rc) is not int or rc!=0 or type(raw) is not bytes or not 0<len(raw)<=1048576:
        raise ValueError('Successful bounded workdir inventory required')
    value=json.loads(raw,object_pairs_hook=_pairs)
    if type(value) is not list or value:
        raise ValueError('Fresh workdir must have an explicitly empty session list')
    return dict(work=work,session_inventory_scope='current_workdir',session_inventory_verified=True,
                previous_sessions=[],inventory_sha256=hashlib.sha256(raw).hexdigest())


def help_options(raw,returncode):
    if type(raw) is not bytes or len(raw)>65536 or type(returncode) is not int or returncode!=0:
        raise ValueError('Successful bounded CLI help required')
    options=sorted(set(re.findall(r'--[a-z][a-z0-9-]{0,63}',raw.decode('utf-8'))))
    if len(options)>64: raise ValueError('Help option count exceeded')
    return options


def summarize(raw,returncode):
    from validation_dispatch_receipt import _pairs
    result=dict(returncode=returncode,kind='invalid',item_count=None,known_fields=[],
                history_verified=False,model_executed=False,scope='current_workdir',list_help_options=[])
    if type(returncode) is not int or type(raw) is not bytes or len(raw)>1048576:
        raise ValueError('Bounded history capture required')
    try:
        value=json.loads(raw,object_pairs_hook=_pairs)
    except (ValueError,UnicodeError): return result
    if type(value) is list:
        result.update(kind='list',item_count=len(value))
        if value and type(value[0]) is dict:
            result['known_fields']=[key for key in FIELDS if key in value[0]]
    elif type(value) is dict:
        result.update(kind='object',known_fields=[key for key in FIELDS if key in value])
    return result


def validate(value):
    if (type(value) is not dict or set(value)!={'returncode','kind','item_count','known_fields',
            'history_verified','model_executed','scope','list_help_options'} or type(value['returncode']) is not int
            or value['kind'] not in ('invalid','list','object')
            or (value['kind']=='list' and (type(value['item_count']) is not int or not 0<=value['item_count']<=1048576))
            or (value['kind']!='list' and value['item_count'] is not None)
            or type(value['known_fields']) is not list or any(key not in FIELDS for key in value['known_fields'])
            or value['history_verified'] is not False or value['model_executed'] is not False
            or value['scope']!='current_workdir'
            or type(value['list_help_options']) is not list or len(value['list_help_options'])>64
            or any(type(s) is not str or re.fullmatch('--[a-z][a-z0-9-]{0,63}',s) is None for s in value['list_help_options'])):
        raise ValueError('Invalid history shape')
    return value


PROBE='''import json,sys,types,hashlib
def module(name,source):
    value=types.ModuleType(name)
    sys.modules[name]=value
    exec(source,value.__dict__)
    return value
prepare=module('guest_mcp_prepare',sys.argv[1])
inspect=module('guest_mcp_inspect',sys.argv[2])
capture=module('mcp_probe_catalog',sys.argv[4])
history=module('mcp_probe_history',sys.argv[5])
inspect.inspect_prepared(sys.argv[3])
from mcp_probe_reservation import _private_directory,CLAIM
from mcp_probe_snapshot import _read,snapshot
from mcp_override_probe import read_global
from validation_dispatch_receipt import _pairs
import os
claim=_private_directory(prepare.STATE+'/'+CLAIM)
try:
    locator=json.loads(_read(claim,'attempt.json',4096)[0],object_pairs_hook=_pairs)
    reservation=json.loads(_read(claim,'reservation.json',1048576)[0],object_pairs_hook=_pairs)
finally: os.close(claim)
original=read_global('config.json')
main=json.loads(original,object_pairs_hook=_pairs)
if type(main) is not dict or main.get('hooks',{})!={} or main.get('mcpServers',{})!={}:
    raise ValueError('Inherited hooks or migration refused')
work=locator['work']
help_raw,help_rc=capture._capture([capture.CLI,'--config',work+'/config.json','list','--help'],work,timeout=5)
options=history.help_options(help_raw,help_rc)
raw,rc=capture._capture([capture.CLI,'--config',work+'/config.json','list','--format','json'],work,timeout=10)
result=history.summarize(raw,rc)
result['list_help_options']=options
snapshot(work,reservation,stage='before')
if read_global('config.json')!=original: raise ValueError('Main config changed')
if hashlib.sha256(read_global('mcp_config.json')).hexdigest().encode()+b'\\n'!=snapshot(work,reservation,stage='before')['inputs']['inherited-mcp.sha256']:
    raise ValueError('MCP config changed')
state=_private_directory(prepare.STATE)
try:
    if _read(state,'prepare-only',1)[0]!=b'': raise ValueError('Hold changed')
finally: os.close(state)
print('EBASE_HISTORY_SHAPE:'+json.dumps(result))
'''
