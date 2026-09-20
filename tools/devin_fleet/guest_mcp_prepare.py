"""Deploy trusted preparation-only modules inside the fixed machine guest.

No CLI/model command is invoked. An existing state directory refuses re-entry.
The caller verifies VM identity, closes network and owns final VM shutdown.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import stat
import types
import zlib

# Fresh, exclusive attempt. The consumed v1 state is retained unchanged.
STATE='/home/agent/.local/state/e-base-mcp-maintenance-v2'
DISCOVERY_STATE='/home/agent/.local/state/e-base-mcp-discovery-v1'
WILDCARD_STATE='/home/agent/.local/state/e-base-mcp-wildcard-v1'
PREVIOUS_CONTROL_STATE='/home/agent/.local/state/e-base-mcp-echo-control-v1'
CONTROL_STATE='/home/agent/.local/state/e-base-mcp-echo-control-v2'
COMPATIBLE_CONTROL_STATE='/home/agent/.local/state/e-base-mcp-echo-compatible-v1'
PARAMS_CONTROL_STATE='/home/agent/.local/state/e-base-mcp-echo-params-v1'
MODULES=('machine_cli_smoke.py','mcp_probe_inputs.py','mcp_probe_reservation.py',
         'mcp_probe_snapshot.py','mcp_probe_binding.py','mcp_probe_audit.py',
         'mcp_denial_fixture.py','mcp_denial_evidence.py','mcp_override_probe.py',
         'validation_dispatch_receipt.py')


def encode_sources(directory):
    sources={}
    for name in MODULES:
        source=(Path(directory)/name).read_text(encoding='utf-8')
        sources[name]={'source':source,'sha256':hashlib.sha256(source.encode()).hexdigest()}
    raw=json.dumps(sources).encode()
    if len(raw)>262144: raise ValueError('Trusted source bundle limit')
    return base64.b64encode(zlib.compress(raw)).decode('ascii')


def decode_sources(encoded):
    if type(encoded) is not str or len(encoded)>65536: raise ValueError('Bundle limit')
    decoder=zlib.decompressobj()
    raw=decoder.decompress(base64.b64decode(encoded,validate=True),262145)
    if len(raw)>262144 or not decoder.eof or decoder.unused_data:
        raise ValueError('Invalid bounded bundle')
    sources=json.loads(raw)
    if type(sources) is not dict or set(sources)!=set(MODULES):
        raise ValueError('Exact trusted modules required')
    for record in sources.values():
        if (type(record) is not dict or set(record)!={'source','sha256'} or type(record['source']) is not str
                or not 0<len(record['source'].encode())<=65536
                or record['sha256']!=hashlib.sha256(record['source'].encode()).hexdigest()):
            raise ValueError('Trusted module digest mismatch')
    return {name:record['source'] for name,record in sources.items()}


def prepare(encoded, *, state_directory=STATE, discovery_source=None):
    if str(state_directory)==PREVIOUS_CONTROL_STATE:
        raise ValueError('Historical control state is read-only')
    # Only the trusted outer controller supplies source bytes. No guest/model
    # path is imported as an alternate builder, and no old attempt is reused.
    if str(state_directory) in (DISCOVERY_STATE,WILDCARD_STATE,CONTROL_STATE,COMPATIBLE_CONTROL_STATE,PARAMS_CONTROL_STATE) and discovery_source is None:
        raise ValueError('Discovery state requires its explicit trusted builder')
    if discovery_source is not None and (str(state_directory) not in (DISCOVERY_STATE,WILDCARD_STATE,CONTROL_STATE,COMPATIBLE_CONTROL_STATE,PARAMS_CONTROL_STATE)
            or type(discovery_source) is not str or not 0<len(discovery_source.encode())<=16384):
        raise ValueError('Fixed discovery preparation and bounded trusted source required')
    sources=decode_sources(encoded)
    state=Path(state_directory)
    if not state.is_absolute() or '..' in state.parts or any(name[:-3] in sys.modules for name in MODULES):
        raise ValueError('Fresh isolated interpreter and absolute state required')
    # The fixed parent already exists in the authenticated guest. No recursive creation.
    parent=os.open('/',os.O_RDONLY|os.O_DIRECTORY)
    try:
        for component in state.parent.parts[1:]:
            child=os.open(component,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent)
            os.close(parent)
            parent=child
        meta=os.fstat(parent)
        if meta.st_uid!=os.getuid() or meta.st_mode & 0o022:
            raise ValueError('Owned protected state parent required')
        os.mkdir(state.name,0o700,dir_fd=parent)
        os.fsync(parent)
    finally: os.close(parent)
    directory=state/'sources'
    hold=os.open(state/'prepare-only',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    try: os.fsync(hold)
    finally: os.close(hold)
    directory.mkdir(mode=0o700)
    for name,source in sources.items():
        fd=os.open(directory/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as stream:
            stream.write(source.encode())
            stream.flush()
            os.fsync(stream.fileno())
    for path in (directory,state):
        fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try: os.fsync(fd)
        finally: os.close(fd)
    sys.path.insert(0,str(directory))
    from mcp_probe_inputs import make_input_builder
    from mcp_probe_reservation import prepare_attempt
    from mcp_probe_snapshot import snapshot
    from mcp_override_probe import read_global
    if discovery_source is not None:
        builder=types.ModuleType('trusted_discovery_builder')
        exec(compile(discovery_source,'<trusted-discovery-builder>','exec'),builder.__dict__)
        make_input_builder=builder.make_input_builder
    original=read_global('mcp_config.json')
    work,reservation=prepare_attempt(state,make_input_builder(original),previous_sessions=[])
    snapshot(work,reservation,stage='before')
    if read_global('mcp_config.json')!=original: raise ValueError('Inherited configuration changed')
    result=dict(prepared=True,model_executed=False,production_admitted=False,
                previous_session_inventory_verified=False,input_count=len(reservation['input_sha256']))
    fd=os.open(state/'prepared.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as stream:
        stream.write(json.dumps(result).encode()); stream.flush(); os.fsync(stream.fileno())
    fd=os.open(state,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try: os.fsync(fd)
    finally: os.close(fd)
    return result


PROBE = """import json,sys,types
module=types.ModuleType('fixed_guest_prepare')
exec(sys.argv[1],module.__dict__)
try:
    result=module.prepare(sys.argv[2])
except Exception:
    result=dict(prepared=False,model_executed=False,production_admitted=False,previous_session_inventory_verified=False,input_count=0)
print('EBASE_MCP_PREPARE:'+json.dumps(result))
"""

DISCOVERY_PROBE = PROBE.replace('module.prepare(sys.argv[2])',
    'module.prepare(sys.argv[2],state_directory=module.DISCOVERY_STATE,discovery_source=sys.argv[3])')
WILDCARD_PROBE = PROBE.replace('module.prepare(sys.argv[2])',
    'module.prepare(sys.argv[2],state_directory=module.WILDCARD_STATE,discovery_source=sys.argv[3])')
CONTROL_PROBE = PROBE.replace('module.prepare(sys.argv[2])',
    'module.prepare(sys.argv[2],state_directory=module.CONTROL_STATE,discovery_source=sys.argv[3])')
COMPATIBLE_CONTROL_PROBE = PROBE.replace('module.prepare(sys.argv[2])',
    'module.prepare(sys.argv[2],state_directory=module.COMPATIBLE_CONTROL_STATE,discovery_source=sys.argv[3])')
PARAMS_CONTROL_PROBE = PROBE.replace('module.prepare(sys.argv[2])',
    'module.prepare(sys.argv[2],state_directory=module.PARAMS_CONTROL_STATE,discovery_source=sys.argv[3])')


def validate(value):
    if (type(value) is not dict or set(value)!={'prepared','model_executed','production_admitted','previous_session_inventory_verified','input_count'}
            or type(value['prepared']) is not bool
            or any(value[k] is not False for k in ('model_executed','production_admitted','previous_session_inventory_verified'))
            or type(value['input_count']) is not int or value['input_count']!=(9 if value['prepared'] else 0)):
        raise ValueError('Invalid preparation receipt')
    return value
