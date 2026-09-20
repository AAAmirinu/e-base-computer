"""Offline fixed CLI interface inspection; never open credentials or auth logs."""
import json
import tempfile

from durable import atomic_write_json
from interactive_machine_auth import run, NAME, UUID
from managed_cli_guard import require_managed_namespace
from sandbox_capacity_probe import ROOT, inventory
from sandbox_runtime import SandboxRuntime
from validation_snapshot_input import _file
from validation_dispatch_receipt import _pairs

PROBE = r'''
import hashlib,json,re,subprocess
from pathlib import Path
path=Path('/home/agent/.local/bin/devin-cli')
with path.open('rb') as stream:
    binary=stream.read(256*1024*1024+1)
if len(binary)>256*1024*1024:
    raise ValueError('CLI binary limit exceeded')
result={'binary_sha256':hashlib.sha256(binary).hexdigest(),'commands':[],
        'credentials_explicitly_read':False,'auth_status_executed':False,'model_executed':False}
for args in (['--version'],['auth','status','--help']):
    proc=subprocess.run([str(path),*args],stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=10)
    if len(proc.stdout)+len(proc.stderr)>65536:
        raise ValueError('CLI help output limit exceeded')
    text=proc.stdout.decode('utf-8',errors='strict')
    # Only public option names and a numeric version leave process memory.
    versions=re.findall(r'(?<![\w.])\d{1,6}\.\d{1,6}\.\d{1,6}(?![\w.])',text)
    result['commands'].append({'args':args,'returncode':proc.returncode,
        'options':sorted(set(re.findall(r'--[a-z][a-z0-9-]{0,63}',text))),
        'versions':versions[:4] if args==['--version'] else []})
# Public installed binary literals only; no credentials, config, or run logs.
markers=(b'Not logged in',b'Logged in as',b'Authenticated as',b'Authentication status')
result['literal_contexts']=[]
for marker in markers:
    start=binary.find(marker)
    if start>=0:
        chunk=binary[max(0,start-80):start+len(marker)+160]
        result['literal_contexts'].append({'marker':marker.decode(),
            'context':''.join(chr(c) if 32<=c<127 else ' ' for c in chunk)})
print(json.dumps(result))
'''


def parse_interface(raw):
    lines=raw.decode('utf-8').splitlines()
    if lines and lines[0]=='Sandbox e-base-machine started successfully':
        lines=lines[1:]
    result=json.loads('\n'.join(lines),object_pairs_hook=_pairs)
    if (not isinstance(result,dict) or set(result)!={'binary_sha256','commands',
            'credentials_explicitly_read','auth_status_executed','model_executed','literal_contexts'}
            or result['credentials_explicitly_read'] is not False
            or result['auth_status_executed'] is not False or result['model_executed'] is not False):
        raise ValueError('Unexpected interface result')
    return result


def compatible_builder():
    from mcp_compatible_control_source import compose
    return compose(_file(ROOT/'mcp_echo_control_inputs.py',16384).decode(),
                   _file(ROOT/'mcp_fixture_compat.py',16384).decode())


def params_builder():
    from mcp_params_control_source import compose
    return compose(*[_file(ROOT/name,16384).decode() for name in (
        'mcp_echo_control_inputs.py','mcp_fixture_compat.py','mcp_fixture_params.py')])


def main(*, status_shape=False, config_locations=False, config_shape=False, mcp_override=False, prepare_mcp=False, inspect_mcp=False, history_shape=False, dispatch_preflight=False, cli_link=False, discovery=False, wildcard=False, cli_policy=False, control=False, compatible=False, params=False):
    if (type(params) is not bool or (params and (prepare_mcp==inspect_mcp or any((compatible,control,discovery,wildcard,cli_policy,status_shape,config_locations,config_shape,mcp_override,history_shape,dispatch_preflight,cli_link))))):
        raise ValueError('Params control is preparation or read-only inspection only')
    if (type(compatible) is not bool or (compatible and (prepare_mcp==inspect_mcp or any((control,discovery,wildcard,cli_policy,status_shape,config_locations,config_shape,mcp_override,history_shape,dispatch_preflight,cli_link))))):
        raise ValueError('Compatible control is preparation or read-only inspection only')
    if (type(control) is not bool or (control and (prepare_mcp==inspect_mcp or any((discovery,wildcard,cli_policy,status_shape,config_locations,config_shape,mcp_override,history_shape,dispatch_preflight,cli_link))))):
        raise ValueError('Control is preparation or read-only inspection only')
    if type(cli_policy) is not bool or (cli_policy and any((status_shape,config_locations,config_shape,mcp_override,prepare_mcp,inspect_mcp,history_shape,dispatch_preflight,cli_link,discovery,wildcard))):
        raise ValueError('Static CLI policy is a separate read-only action')
    if (type(wildcard) is not bool or (wildcard and (discovery or prepare_mcp==inspect_mcp
            or any((status_shape,config_locations,config_shape,mcp_override,history_shape,dispatch_preflight,cli_link))))):
        raise ValueError('Wildcard is preparation or read-only inspection only')
    if type(discovery) is not bool or (discovery and (prepare_mcp==inspect_mcp)):
        raise ValueError('Discovery is preparation or read-only inspection only')
    require_managed_namespace()
    registration=json.loads(_file(ROOT/'sandbox-registry.json',1024*1024),object_pairs_hook=_pairs)
    entry=registration['roles']['machine']
    if entry.get('name')!=NAME or entry.get('id')!=UUID:
        raise ValueError('Fixed machine identity required')
    work=ROOT/tempfile.mkdtemp(prefix='mcp-prepared-state-' if inspect_mcp else 'mcp-prepare-' if prepare_mcp else 'mcp-override-' if mcp_override else 'mcp-shape-' if config_shape else 'mcp-locations-' if config_locations else 'auth-shape-' if status_shape else 'auth-interface-',dir=ROOT)
    record={'schema':1,'phase':'checking','all_vms_stopped':False,
            'network_changed':False,'authentication_verified':False}
    atomic_write_json(work/'receipt.json',record)
    try:
        with SandboxRuntime(registration,work) as runtime:
            inventory(registration)
            rules=json.loads(run('policy','ls',NAME,'--json'))['rules']
            if not any(r.get('scope')=='sandbox:'+NAME and r.get('resource_type')=='network'
                       and r.get('status')=='active' and r.get('decision')=='deny'
                       and r.get('resources')==['**'] for r in rules):
                raise RuntimeError('Existing blanket network denial required')
            with runtime.role('machine') as repo:
                command=['/usr/bin/python3','-I','-c',PROBE]
                if cli_policy:
                    from mcp_cli_policy_static import PROBE as policy_probe
                    command=['/usr/bin/python3','-I','-c',policy_probe,
                        _file(ROOT/'mcp_cli_identity.py',16384).decode(),
                        _file(ROOT/'mcp_cli_policy_static.py',16384).decode()]
                elif cli_link:
                    from mcp_cli_identity import PROBE as link_probe
                    command=['/usr/bin/python3','-I','-c',link_probe,_file(ROOT/'mcp_cli_identity.py',16384).decode()]
                elif dispatch_preflight:
                    from guest_mcp_dispatch import PROBE as dispatch_probe,encode_support
                    from guest_mcp_prepare import encode_sources
                    command=['/usr/bin/python3','-I','-c',dispatch_probe,
                             _file(ROOT/'guest_mcp_prepare.py',16384).decode('utf-8'),
                             _file(ROOT/'guest_mcp_inspect.py',16384).decode('utf-8'),encode_sources(ROOT),
                             encode_support(ROOT),_file(ROOT/'guest_mcp_dispatch.py',16384).decode('utf-8'),'preflight']
                elif history_shape:
                    from mcp_probe_history import PROBE as history_probe
                    from guest_mcp_prepare import encode_sources
                    command=['/usr/bin/python3','-I','-c',history_probe,
                             _file(ROOT/'guest_mcp_prepare.py',16384).decode('utf-8'),
                             _file(ROOT/'guest_mcp_inspect.py',16384).decode('utf-8'),encode_sources(ROOT),
                             _file(ROOT/'mcp_probe_catalog.py',16384).decode('utf-8'),
                             _file(ROOT/'mcp_probe_history.py',16384).decode('utf-8')]
                elif inspect_mcp:
                    from guest_mcp_inspect import PROBE as inspect_probe
                    from guest_mcp_prepare import encode_sources
                    if discovery:
                        from guest_mcp_inspect import DISCOVERY_PROBE as inspect_probe
                    if wildcard:
                        from guest_mcp_inspect import WILDCARD_PROBE as inspect_probe
                    if control:
                        from guest_mcp_inspect import CONTROL_PROBE as inspect_probe
                    if compatible:
                        from guest_mcp_inspect import COMPATIBLE_CONTROL_PROBE as inspect_probe
                    if params:
                        from guest_mcp_inspect import PARAMS_CONTROL_PROBE as inspect_probe
                    command=['/usr/bin/python3','-I','-c',inspect_probe,
                             _file(ROOT/'guest_mcp_prepare.py',16384).decode('utf-8'),
                             _file(ROOT/'guest_mcp_inspect.py',16384).decode('utf-8'),encode_sources(ROOT)]
                    if discovery: command.append(_file(ROOT/'mcp_discovery_inputs.py',16384).decode())
                    if wildcard: command.append(_file(ROOT/'mcp_wildcard_denial_inputs.py',16384).decode())
                    if control: command.append(_file(ROOT/'mcp_echo_control_inputs.py',16384).decode())
                    if compatible: command.append(compatible_builder())
                    if params: command.append(params_builder())
                elif prepare_mcp:
                    from guest_mcp_prepare import PROBE as prepare_probe, encode_sources
                    if discovery:
                        from guest_mcp_prepare import DISCOVERY_PROBE as prepare_probe
                    if wildcard:
                        from guest_mcp_prepare import WILDCARD_PROBE as prepare_probe
                    if control:
                        from guest_mcp_prepare import CONTROL_PROBE as prepare_probe
                    if compatible:
                        from guest_mcp_prepare import COMPATIBLE_CONTROL_PROBE as prepare_probe
                    if params:
                        from guest_mcp_prepare import PARAMS_CONTROL_PROBE as prepare_probe
                    command=['/usr/bin/python3','-I','-c',prepare_probe,
                             _file(ROOT/'guest_mcp_prepare.py',16384).decode('utf-8'),encode_sources(ROOT)]
                    if discovery: command.append(_file(ROOT/'mcp_discovery_inputs.py',16384).decode())
                    if wildcard: command.append(_file(ROOT/'mcp_wildcard_denial_inputs.py',16384).decode())
                    if control: command.append(_file(ROOT/'mcp_echo_control_inputs.py',16384).decode())
                    if compatible: command.append(compatible_builder())
                    if params: command.append(params_builder())
                elif mcp_override:
                    from mcp_override_probe import PROBE as override_probe
                    command=['/usr/bin/python3','-I','-c',override_probe,
                             _file(ROOT/'mcp_override_probe.py',16384).decode('utf-8')]
                elif config_shape:
                    from mcp_config_shape import PROBE as shape_probe
                    command=['/usr/bin/python3','-I','-c',shape_probe,
                             _file(ROOT/'mcp_config_shape.py',16384).decode('utf-8')]
                elif config_locations:
                    from mcp_config_locations import PROBE as config_probe
                    command=['/usr/bin/python3','-I','-c',config_probe,
                             _file(ROOT/'mcp_config_locations.py',16384).decode('utf-8')]
                elif status_shape:
                    from auth_status_shape import PROBE as status_probe
                    command=['/usr/bin/python3','-I','-c',status_probe,
                             _file(ROOT/'auth_status_shape.py',32768).decode('utf-8')]
                completed=repo.controller.execute(command,
                    cwd='/',log_path=work/'interface.json',timeout=30,max_log_bytes=8192,
                    external_stop=repo.external_stop)
                if completed.returncode:
                    raise RuntimeError('CLI interface inspection failed')
                raw=_file(work/'interface.json',8192)
                if cli_policy:
                    from mcp_cli_policy_static import validate as validate_policy
                    prefix='EBASE_CLI_POLICY:'
                    lines=[line[len(prefix):] for line in raw.decode().splitlines() if line.startswith(prefix)]
                    if len(lines)!=1:raise ValueError('Exact static policy evidence required')
                    record['cli_policy']=validate_policy(json.loads(lines[0],object_pairs_hook=_pairs))
                elif cli_link:
                    from mcp_cli_identity import validate_metadata
                    prefix='EBASE_CLI_LINK:'
                    lines=[line[len(prefix):] for line in raw.decode().splitlines() if line.startswith(prefix)]
                    if len(lines)!=1: raise ValueError('Missing CLI link metadata')
                    record['cli_link']=validate_metadata(json.loads(lines[0],object_pairs_hook=_pairs))
                elif dispatch_preflight:
                    from guest_mcp_dispatch import validate_preflight
                    prefix='EBASE_MCP_DISPATCH:'
                    lines=[line[len(prefix):] for line in raw.decode('utf-8').splitlines() if line.startswith(prefix)]
                    if len(lines)!=1: raise ValueError('Missing dispatch preflight')
                    record['dispatch_preflight']=validate_preflight(json.loads(lines[0],object_pairs_hook=_pairs))
                elif history_shape:
                    from mcp_probe_history import validate
                    prefix='EBASE_HISTORY_SHAPE:'
                    lines=[line[len(prefix):] for line in raw.decode('utf-8').splitlines() if line.startswith(prefix)]
                    if len(lines)!=1: raise ValueError('Missing history shape')
                    record['history_shape']=validate(json.loads(lines[0],object_pairs_hook=_pairs))
                elif inspect_mcp:
                    from guest_mcp_inspect import validate
                    prefix='EBASE_MCP_PREPARED_STATE:'
                    lines=[line[len(prefix):] for line in raw.decode('utf-8').splitlines() if line.startswith(prefix)]
                    if len(lines)!=1:
                        raise ValueError('Missing saved-state observation')
                    record['mcp_prepared_state']=validate(json.loads(lines[0],object_pairs_hook=_pairs))
                elif prepare_mcp:
                    from guest_mcp_prepare import validate
                    prefix='EBASE_MCP_PREPARE:'
                    lines=[line[len(prefix):] for line in raw.decode('utf-8').splitlines() if line.startswith(prefix)]
                    if len(lines)!=1:
                        raise ValueError('Missing fixed preparation receipt')
                    record['mcp_prepare']=validate(json.loads(lines[0],object_pairs_hook=_pairs))
                elif mcp_override:
                    from mcp_override_probe import validate
                    prefix='EBASE_MCP_OVERRIDE:'
                    lines=[line[len(prefix):] for line in raw.decode('utf-8').splitlines() if line.startswith(prefix)]
                    if len(lines)!=1:
                        raise ValueError('Missing fixed override observation')
                    record['mcp_override']=validate(json.loads(lines[0],object_pairs_hook=_pairs))
                elif config_shape:
                    from mcp_config_shape import validate
                    prefix='EBASE_MCP_SHAPE:'
                    lines=[line[len(prefix):] for line in raw.decode('utf-8').splitlines() if line.startswith(prefix)]
                    if len(lines)!=1:
                        raise ValueError('Missing fixed config shape')
                    record['config_shape']=validate(json.loads(lines[0],object_pairs_hook=_pairs))
                elif config_locations:
                    from mcp_config_locations import validate
                    prefix='EBASE_MCP_LOCATIONS:'
                    lines=[line[len(prefix):] for line in raw.decode('utf-8').splitlines() if line.startswith(prefix)]
                    if len(lines)!=1:
                        raise ValueError('Missing fixed configuration metadata')
                    record['config_locations']=validate(json.loads(lines[0],object_pairs_hook=_pairs))
                elif status_shape:
                    from auth_status_shape import summarize
                    prefix='EBASE_AUTH_SHAPE:'
                    lines=[line[len(prefix):] for line in raw.decode('utf-8').splitlines()
                           if line.startswith(prefix)]
                    if len(lines)!=1:
                        raise ValueError('Missing or ambiguous status shape')
                    value=json.loads(lines[0],object_pairs_hook=_pairs)
                    expected=summarize(b'',0)
                    if (not isinstance(value,dict) or set(value)!=set(expected)
                            or value['authentication_verified'] is not False
                            or value['model_executed'] is not False
                            or value['raw_output_suppressed'] is not True
                            or type(value['returncode']) is not int
                            or type(value['line_count']) is not int or not 0<=value['line_count']<=65536
                            or not isinstance(value['markers'],dict)
                            or set(value['markers'])!=set(expected['markers'])
                            or any(type(n) is not int or not 0<=n<=value['line_count']
                                   for n in value['markers'].values())):
                        raise ValueError('Invalid status shape')
                    record['status_shape']=value
                else:
                    record['interface']=parse_interface(raw)
            inventory(registration)
            record.update(phase='complete',all_vms_stopped=True)
    finally:
        atomic_write_json(work/'receipt.json',record)
    print(json.dumps({'evidence':str(work),**record}),flush=True)


if __name__=='__main__':
    import sys
    if sys.argv[1:] in (['--prepare-mcp-params'],['--inspect-mcp-params']):
        main(prepare_mcp=sys.argv[1:]==['--prepare-mcp-params'],
             inspect_mcp=sys.argv[1:]==['--inspect-mcp-params'],params=True)
        sys.exit(0)
    if sys.argv[1:] in (['--prepare-mcp-compatible'],['--inspect-mcp-compatible']):
        main(prepare_mcp=sys.argv[1:]==['--prepare-mcp-compatible'],
             inspect_mcp=sys.argv[1:]==['--inspect-mcp-compatible'],compatible=True)
        sys.exit(0)
    if sys.argv[1:] in (['--prepare-mcp-control'],['--inspect-mcp-control']):
        main(prepare_mcp=sys.argv[1:]==['--prepare-mcp-control'],
             inspect_mcp=sys.argv[1:]==['--inspect-mcp-control'],control=True)
        sys.exit(0)
    if sys.argv[1:]==['--cli-policy']:
        main(cli_policy=True)
        sys.exit(0)
    if sys.argv[1:] in (['--prepare-mcp-wildcard'],['--inspect-mcp-wildcard']):
        main(prepare_mcp=sys.argv[1:] == ['--prepare-mcp-wildcard'],
             inspect_mcp=sys.argv[1:] == ['--inspect-mcp-wildcard'],wildcard=True)
        sys.exit(0)
    if sys.argv[1:]==['--prepare-mcp-discovery']:
        main(prepare_mcp=True,discovery=True)
        sys.exit(0)
    if sys.argv[1:]==['--inspect-mcp-discovery']:
        main(inspect_mcp=True,discovery=True)
        sys.exit(0)
    if sys.argv[1:]==['--cli-link']:
        main(cli_link=True)
        sys.exit(0)
    if sys.argv[1:] not in ([],['--status-shape'],['--config-locations'],['--config-shape'],['--mcp-override'],['--prepare-mcp'],['--inspect-mcp'],['--history-shape'],['--dispatch-preflight']):
        raise ValueError('Unknown inspection action')
    main(status_shape=sys.argv[1:]==['--status-shape'],config_locations=sys.argv[1:]==['--config-locations'],config_shape=sys.argv[1:]==['--config-shape'],mcp_override=sys.argv[1:]==['--mcp-override'],prepare_mcp=sys.argv[1:]==['--prepare-mcp'],inspect_mcp=sys.argv[1:]==['--inspect-mcp'],history_shape=sys.argv[1:]==['--history-shape'],dispatch_preflight=sys.argv[1:]==['--dispatch-preflight'])
