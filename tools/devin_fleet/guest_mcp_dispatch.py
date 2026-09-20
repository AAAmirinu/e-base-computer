"""Trusted guest dispatch for the prepared one-shot probe; no public CLI.

The outer controller must keep its checked lease/lock/network window alive until
this bounded command ends, restore denial and stop the VM. Returned process
metadata is not permission acceptance or evidence of all descendants stopping.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
import types
import zlib

from guest_mcp_prepare import STATE
from mcp_probe_reservation import CLAIM,_private_directory
from mcp_probe_snapshot import _read,snapshot
from mcp_probe_supervision import validate_receipt
from mcp_probe_history import read_empty_workdir_inventory
from mcp_probe_launch import launch_reserved,check_main_config,check_inherited
from model_catalog_policy import _unique,_reject_constant
from mcp_cli_identity import verify_cli

SUPPORT=('model_catalog_policy','mcp_probe_process','mcp_probe_catalog',
         'mcp_probe_supervision','mcp_probe_history','mcp_cli_identity','mcp_probe_launch','mcp_probe_collect')


def encode_support(directory):
    payload={}
    for name in SUPPORT:
        source=(Path(directory)/(name+'.py')).read_text(encoding='utf-8')
        payload[name]=dict(source=source,sha256=hashlib.sha256(source.encode()).hexdigest())
    raw=json.dumps(payload).encode()
    if len(raw)>262144: raise ValueError('Support source bound')
    return base64.b64encode(zlib.compress(raw)).decode('ascii')


def decode_support(encoded):
    if type(encoded) is not str or len(encoded)>65536: raise ValueError('Support bundle bound')
    decoder=zlib.decompressobj()
    raw=decoder.decompress(base64.b64decode(encoded,validate=True),262145)
    if len(raw)>262144 or not decoder.eof or decoder.unused_data: raise ValueError('Support bundle invalid')
    value=json.loads(raw,object_pairs_hook=_unique,parse_constant=_reject_constant)
    if type(value) is not dict or set(value)!=set(SUPPORT): raise ValueError('Exact support modules required')
    for record in value.values():
        if (type(record) is not dict or set(record)!={'source','sha256'} or type(record['source']) is not str
                or not 0<len(record['source'].encode())<=65536
                or record['sha256']!=hashlib.sha256(record['source'].encode()).hexdigest()):
            raise ValueError('Support source mismatch')
    return {name:record['source'] for name,record in value.items()}


def read_binding(state_directory=STATE):
    claim=_private_directory(Path(state_directory)/CLAIM)
    try:
        if set(os.listdir(claim))!={'attempt.json','reservation.json'}:
            raise ValueError('Fresh unconsumed claim required')
        locator=json.loads(_read(claim,'attempt.json',4096)[0],object_pairs_hook=_unique)
        raw=_read(claim,'reservation.json',1048576)[0]
        reservation=json.loads(raw,object_pairs_hook=_unique)
    finally: os.close(claim)
    if (type(locator) is not dict or set(locator)!={'nonce','work','phase'} or locator['phase']!='preparing'
            or type(locator['nonce']) is not str or re.fullmatch('[0-9a-f]{32}',locator['nonce']) is None
            or type(locator['work']) is not str or re.fullmatch('/tmp/e-base-mcp-probe-[a-z0-9_]{8}',locator['work']) is None
            or type(reservation) is not dict or reservation.get('nonce')!=locator['nonce']):
        raise ValueError('Fixed reservation locator required')
    return dict(nonce=locator['nonce'],work=locator['work'],reservation_sha256=hashlib.sha256(raw).hexdigest()),raw


def preflight(state_directory=STATE):
    """Call only after trusted prepared-state inspection in this same process."""
    binding,raw=read_binding(state_directory)
    reservation=json.loads(raw,object_pairs_hook=_unique,parse_constant=_reject_constant)
    check_inherited(snapshot(binding['work'],reservation,stage='before')['inputs'])
    before=check_main_config()
    verify_cli()
    inventory=read_empty_workdir_inventory(binding['work'],timeout=10)
    if check_main_config()!=before: raise ValueError('Main config changed during inventory')
    check_inherited(snapshot(binding['work'],reservation,stage='before')['inputs'])
    after,after_raw=read_binding(state_directory)
    if after!=binding or after_raw!=raw: raise ValueError('Reservation changed during inventory')
    return dict(binding,inventory=inventory,model_executed=False,production_admitted=False)


def dispatch(admission_raw,*,state_directory=STATE):
    binding,reservation_raw=read_binding(state_directory)
    receipt=validate_receipt(admission_raw,nonce=binding['nonce'],reservation_raw=reservation_raw,
                             work=binding['work'],now=time.time())
    def verify(**requested):
        timeout=requested.pop('timeout')
        if requested!=binding: raise ValueError('Dispatch binding changed')
        budget=min(10,timeout,receipt['expires_at']-time.time())
        if budget<=0: raise ValueError('Dispatch admission expired')
        observed=read_empty_workdir_inventory(binding['work'],timeout=budget)
        if (observed['previous_sessions']!=receipt['previous_sessions']
                or observed['work']!=receipt['work']):
            raise ValueError('Workdir inventory changed')
        return admission_raw
    return launch_reserved(state_directory,supervised_check=verify)


def validate_preflight(value):
    if (type(value) is not dict or set(value)!={'nonce','work','reservation_sha256','inventory','model_executed','production_admitted'}
            or type(value['nonce']) is not str or re.fullmatch('[0-9a-f]{32}',value['nonce']) is None
            or type(value['work']) is not str or re.fullmatch('/tmp/e-base-mcp-probe-[a-z0-9_]{8}',value['work']) is None
            or type(value['reservation_sha256']) is not str or re.fullmatch('[0-9a-f]{64}',value['reservation_sha256']) is None
            or value['model_executed'] is not False or value['production_admitted'] is not False):
        raise ValueError('Invalid preflight binding')
    inventory=value['inventory']
    if (type(inventory) is not dict or set(inventory)!={'work','session_inventory_scope','session_inventory_verified','previous_sessions','inventory_sha256'}
            or inventory['work']!=value['work'] or inventory['session_inventory_scope']!='current_workdir'
            or inventory['session_inventory_verified'] is not True or inventory['previous_sessions']!=[]
            or type(inventory['inventory_sha256']) is not str or re.fullmatch('[0-9a-f]{64}',inventory['inventory_sha256']) is None):
        raise ValueError('Invalid scoped preflight inventory')
    return value


# The outer caller supplies only reviewed controller sources, never model files.
# Bootstrap imports standard library only until the baseline inspector loads its
# exact trusted modules. Support modules are loaded from decoded outer bytes.
PROBE='''import sys,types,json,base64,zlib,hashlib
def module(name,source):
    value=types.ModuleType(name); sys.modules[name]=value
    exec(compile(source,'<trusted-'+name+'>','exec'),value.__dict__)
    return value
prepare=module('guest_mcp_prepare',sys.argv[1])
inspect=module('guest_mcp_inspect',sys.argv[2])
if sys.argv[6]=='collect' and len(sys.argv)==9:
    sources=prepare.decode_sources(sys.argv[3])
    if any(name in sys.modules for name in inspect.ORDER): raise ValueError('Fresh collection interpreter required')
    for name in inspect.ORDER:
        value=types.ModuleType(name)
        value.__file__=prepare.STATE+'/sources/'+name+'.py'
        sys.modules[name]=value
        exec(compile(sources[name+'.py'],'<trusted-'+name+'>','exec'),value.__dict__)
else:
    inspect.inspect_prepared(sys.argv[3])
# Decode using a standalone copy of the trusted decoder, avoiding imports of
# launch modules before their dependencies have been supplied.
from validation_dispatch_receipt import _pairs
decoder=zlib.decompressobj()
if len(sys.argv[4])>65536: raise ValueError('Support bound')
raw=decoder.decompress(base64.b64decode(sys.argv[4],validate=True),262145)
if len(raw)>262144 or not decoder.eof or decoder.unused_data: raise ValueError('Support bound')
payload=json.loads(raw,object_pairs_hook=_pairs)
order=('model_catalog_policy','mcp_probe_process','mcp_probe_catalog','mcp_probe_supervision','mcp_probe_history','mcp_cli_identity','mcp_probe_launch','mcp_probe_collect')
if type(payload) is not dict or set(payload)!=set(order) or any(name in sys.modules for name in order):
    raise ValueError('Fresh exact support required')
for name in order:
    record=payload[name]
    if type(record) is not dict or set(record)!={'source','sha256'} or type(record['source']) is not str or not 0<len(record['source'].encode())<=65536 or hashlib.sha256(record['source'].encode()).hexdigest()!=record['sha256']:
        raise ValueError('Support mismatch')
for name in order: module(name,payload[name]['source'])
dispatch=module('guest_mcp_dispatch',sys.argv[5])
if sys.argv[6]=='preflight':
    result=dispatch.preflight()
elif sys.argv[6]=='dispatch' and len(sys.argv)==8:
    result=dispatch.dispatch(sys.argv[7].encode())
elif sys.argv[6]=='collect' and len(sys.argv)==9:
    result=sys.modules['mcp_probe_collect'].collect(sys.argv[7].encode(),inspection_lease_id=sys.argv[8])
else: raise ValueError('Fixed dispatch action required')
print('EBASE_MCP_DISPATCH:'+json.dumps(result))
'''
