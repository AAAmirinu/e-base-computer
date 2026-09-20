"""Read-only inspection of the existing fixed guest preparation; no repair/retry."""
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import stat
import types
from guest_mcp_prepare import STATE, DISCOVERY_STATE, WILDCARD_STATE, CONTROL_STATE, MODULES, decode_sources, validate as validate_prepared
from guest_mcp_prepare import COMPATIBLE_CONTROL_STATE, PARAMS_CONTROL_STATE

ORDER=('machine_cli_smoke','mcp_probe_audit','mcp_denial_fixture','mcp_denial_evidence',
       'validation_dispatch_receipt','mcp_override_probe','mcp_probe_binding','mcp_probe_inputs',
       'mcp_probe_reservation','mcp_probe_snapshot')


def inspect_prepared(encoded, *, state_directory=STATE):
    sources=decode_sources(encoded)
    if any(name in sys.modules for name in ORDER):
        raise ValueError('Fresh isolated inspection interpreter required')
    for name in ORDER:
        module=types.ModuleType(name)
        module.__file__=str(Path(state_directory)/'sources'/(name+'.py'))
        sys.modules[name]=module
        exec(compile(sources[name+'.py'],module.__file__,'exec'),module.__dict__)
    from mcp_probe_reservation import _private_directory, CLAIM
    from mcp_probe_snapshot import _read, snapshot
    from mcp_override_probe import read_global
    from validation_dispatch_receipt import _pairs
    handles=[]
    def directory(path):
        fd=_private_directory(path); handles.append(fd); return fd
    def record(parent,name):
        return json.loads(_read(parent,name,1048576)[0],object_pairs_hook=_pairs)
    try:
        state=directory(state_directory)
        source_dir=directory(Path(state_directory)/'sources')
        if set(os.listdir(state))!={'sources','prepare-only',CLAIM,'prepared.json'}:
            raise ValueError('Unexpected state entry')
        entries=set(os.listdir(source_dir))
        if entries not in (set(MODULES),set(MODULES)|{'__pycache__'}):
            raise ValueError('Unexpected source entry')
        if '__pycache__' in entries:
            cache=os.stat('__pycache__',dir_fd=source_dir,follow_symlinks=False)
            if not stat.S_ISDIR(cache.st_mode) or cache.st_uid!=os.getuid() or cache.st_mode & 0o022:
                raise ValueError('Unsafe inert cache directory')
        for name,expected in sources.items():
            if _read(source_dir,name,65536)[0]!=expected.encode():
                raise ValueError('Stored controller source changed')
        if _read(state,'prepare-only',1)[0]!=b'': raise ValueError('Invalid preparation hold')
        prepared=validate_prepared(record(state,'prepared.json'))
        if not prepared['prepared']: raise ValueError('Preparation incomplete')
        claim=directory(Path(state_directory)/CLAIM)
        if set(os.listdir(claim))!={'attempt.json','reservation.json'}:
            raise ValueError('Attempt already started or claim changed')
        locator=record(claim,'attempt.json')
        reservation=record(claim,'reservation.json')
        if (type(locator) is not dict or set(locator)!={'work','nonce','phase'} or locator['phase']!='preparing'
                or type(locator['nonce']) is not str or re.fullmatch('[0-9a-f]{32}',locator['nonce']) is None
                or type(reservation) is not dict or reservation.get('nonce')!=locator['nonce']
                or type(reservation.get('schema')) is not int or reservation['schema']!=1
                or reservation.get('phase')!='reserved'):
            raise ValueError('Reservation locator mismatch')
        captured=snapshot(locator['work'],reservation,stage='before')
        expected=captured['inputs']['inherited-mcp.sha256']
        if hashlib.sha256(read_global('mcp_config.json')).hexdigest().encode()+b'\n'!=expected:
            raise ValueError('Inherited MCP configuration changed')
        return dict(prepared_state_verified=True,prepare_only_retained=True,launch_absent=True,
                    input_count=len(captured['inputs']),model_executed=False,production_admitted=False)
    finally:
        for fd in reversed(handles): os.close(fd)


def inspect_discovery(encoded, source):
    return _inspect_profile(encoded,source,DISCOVERY_STATE)


def inspect_wildcard(encoded, source):
    return _inspect_profile(encoded,source,WILDCARD_STATE)


def _inspect_profile(encoded, source, state_directory):
    if state_directory not in (DISCOVERY_STATE,WILDCARD_STATE,CONTROL_STATE,COMPATIBLE_CONTROL_STATE,PARAMS_CONTROL_STATE):
        raise ValueError('Fixed profile state required')
    if type(source) is not str or not 0<len(source.encode())<=16384:
        raise ValueError('Bounded trusted discovery builder required')
    result=inspect_prepared(encoded,state_directory=state_directory)
    builder=types.ModuleType('trusted_discovery_inspection')
    exec(compile(source,'<trusted-discovery-builder>','exec'),builder.__dict__)
    from mcp_probe_reservation import _private_directory, CLAIM
    from mcp_probe_snapshot import _read, snapshot
    from mcp_override_probe import read_global
    from validation_dispatch_receipt import _pairs
    claim=_private_directory(Path(state_directory)/CLAIM)
    try:
        locator_read=_read(claim,'attempt.json',4096)
        reservation_read=_read(claim,'reservation.json',1048576)
        locator_raw=locator_read[0]
        reservation_raw=reservation_read[0]
        locator=json.loads(locator_raw,object_pairs_hook=_pairs)
        reservation=json.loads(reservation_raw,object_pairs_hook=_pairs)
        if (type(locator) is not dict or set(locator)!={'work','nonce','phase'}
                or locator['phase']!='preparing' or type(locator['nonce']) is not str
                or re.fullmatch('[0-9a-f]{32}',locator['nonce']) is None
                or type(locator['work']) is not str or re.fullmatch('/tmp/e-base-mcp-probe-[a-z0-9_]{8}',locator['work']) is None
                or type(reservation) is not dict or reservation.get('nonce')!=locator['nonce']
                or type(reservation.get('schema')) is not int or reservation['schema']!=1
                or reservation.get('phase')!='reserved'):
            raise ValueError('Discovery reservation changed')
        captured=snapshot(locator['work'],reservation,stage='before')
        inherited=read_global('mcp_config.json')
        expected=builder.make_input_builder(inherited)(locator['work'],locator['nonce'],tuple(reservation['audit_identity']))
        captured=snapshot(locator['work'],reservation,stage='before')
        if (captured['inputs']!=expected or read_global('mcp_config.json')!=inherited
                or _read(claim,'attempt.json',4096)!=locator_read
                or _read(claim,'reservation.json',1048576)!=reservation_read
                or set(os.listdir(claim))!={'attempt.json','reservation.json'}):
            raise ValueError('Exact unused discovery inputs required')
        state=_private_directory(state_directory)
        try:
            if _read(state,'prepare-only',1)[0]!=b'': raise ValueError('Discovery hold changed')
        finally: os.close(state)
    finally: os.close(claim)
    return result


def inspect_control(encoded,source):
    return _inspect_profile(encoded,source,CONTROL_STATE)


def inspect_compatible_control(encoded,source):
    return _inspect_profile(encoded,source,COMPATIBLE_CONTROL_STATE)


def inspect_params_control(encoded,source):
    return _inspect_profile(encoded,source,PARAMS_CONTROL_STATE)


PROBE="""import json,sys,types
prepare=types.ModuleType('guest_mcp_prepare')
sys.modules['guest_mcp_prepare']=prepare
exec(sys.argv[1],prepare.__dict__)
module=types.ModuleType('fixed_guest_inspect')
exec(sys.argv[2],module.__dict__)
try:
    result=module.inspect_prepared(sys.argv[3])
except Exception:
    result=dict(prepared_state_verified=False,prepare_only_retained=False,launch_absent=False,input_count=0,model_executed=False,production_admitted=False)
print('EBASE_MCP_PREPARED_STATE:'+json.dumps(result))
"""

DISCOVERY_PROBE=PROBE.replace('module.inspect_prepared(sys.argv[3])',
                             'module.inspect_discovery(sys.argv[3],sys.argv[4])')
WILDCARD_PROBE=PROBE.replace('module.inspect_prepared(sys.argv[3])',
                            'module.inspect_wildcard(sys.argv[3],sys.argv[4])')
CONTROL_PROBE=PROBE.replace('module.inspect_prepared(sys.argv[3])',
                           'module.inspect_control(sys.argv[3],sys.argv[4])')
COMPATIBLE_CONTROL_PROBE=PROBE.replace('module.inspect_prepared(sys.argv[3])',
                           'module.inspect_compatible_control(sys.argv[3],sys.argv[4])')
PARAMS_CONTROL_PROBE=PROBE.replace('module.inspect_prepared(sys.argv[3])',
                           'module.inspect_params_control(sys.argv[3],sys.argv[4])')


def validate(value):
    if (type(value) is not dict or set(value)!={'prepared_state_verified','prepare_only_retained','launch_absent','input_count','model_executed','production_admitted'}
            or any(type(value[k]) is not bool for k in ('prepared_state_verified','prepare_only_retained','launch_absent'))
            or value['model_executed'] is not False or value['production_admitted'] is not False
            or type(value['input_count']) is not int or value['input_count']!=(9 if value['prepared_state_verified'] else 0)
            or value['prepare_only_retained']!=value['prepared_state_verified'] or value['launch_absent']!=value['prepared_state_verified']):
        raise ValueError('Invalid saved-state observation')
    return value
