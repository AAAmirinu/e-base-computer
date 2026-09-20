"""One reserved catalog-only diagnostic, separate from the consumed MCP probe."""
import json
import os
import tempfile
from pathlib import Path
from durable import atomic_write_json
from machine_cli_smoke import DENY
from managed_cli_guard import require_managed_namespace
from mcp_maintenance_network import catalog_diagnostic_network,IMAGE
from mcp_maintenance_restart import CATALOG_RUN,MACHINE
from mcp_probe_entry import interruption_cleanup
from model_network_admission import check_network
from observed_boundary_admission import make_boundary_check
from sandbox_capacity_probe import ROOT,inventory
from sandbox_runtime import SandboxRuntime
from validation_dispatch_receipt import _pairs
from validation_snapshot_input import _file
from turn_validation_result import same_json

MODULES=('mcp_override_probe','mcp_cli_identity','mcp_probe_catalog','model_catalog_policy','catalog_endpoint_probe')
PROBE=r'''
import sys,types,json,tempfile,os
from pathlib import Path
from datetime import datetime,timezone
names=('mcp_override_probe','mcp_cli_identity','mcp_probe_catalog','model_catalog_policy','catalog_endpoint_probe')
for name,source in zip(names,sys.argv[1:6]):
    module=types.ModuleType(name);sys.modules[name]=module
    exec(compile(source,'<trusted-'+name+'>','exec'),module.__dict__)
from mcp_override_probe import read_global,overrides,pairs
from mcp_cli_identity import verify_cli,CLI
from mcp_probe_catalog import _capture,CaptureDeadline
from model_catalog_policy import require_free_model,MODEL
from catalog_endpoint_probe import probe_endpoints
def collect():
    main=read_global('config.json'); inherited=read_global('mcp_config.json')
    settings=json.loads(main,object_pairs_hook=pairs)
    if type(settings) is not dict or settings.get('hooks',{})!={} or settings.get('mcpServers',{})!={}:
        raise ValueError('Inherited hooks or pending migration refused')
    servers=overrides(inherited);del servers['fleet-probe']
    work=Path(tempfile.mkdtemp(prefix='e-base-catalog-diagnostic-',dir='/tmp'))
    os.chmod(work,0o700)
    for directory in ('.git','.git/objects','.git/refs','.devin'):
        (work/directory).mkdir(mode=0o700)
    config=dict(version=1,shell={'setup_complete':True},notify='never',agent={'model':MODEL},
        read_config_from={'cursor':False,'windsurf':False,'claude':False},
        permissions={'deny':json.loads(sys.argv[6]),'allow':[]})
    inputs={'config.json':json.dumps(config).encode(),'.devin/mcp_config.json':json.dumps({'mcpServers':servers}).encode(),
        '.git/HEAD':b'ref: refs/heads/diagnostic\n','.git/config':b'[core]\nrepositoryformatversion = 0\nbare = false\n'}
    for name,raw in inputs.items():
        fd=os.open(work/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(raw)
    verify_cli()
    endpoints=probe_endpoints()
    result=None
    try:
        raw,code=_capture([CLI,'--config',str(work/'config.json'),'models','list','--format','json'],str(work),timeout=60,diagnostic=True)
        result=dict(catalog_verified=True,**require_free_model(raw,code,now=datetime.now(timezone.utc)))
    except CaptureDeadline as error:
        result=dict(catalog_verified=False,error_type='CaptureDeadline',observation=error.observation,model_executed=False)
    except (ValueError,OSError):
        result=dict(catalog_verified=False,error_type='CatalogUnavailableOrRejected',model_executed=False)
    if main!=read_global('config.json') or inherited!=read_global('mcp_config.json'):
        raise ValueError('Inherited configuration changed')
    if any((work/name).read_bytes()!=raw for name,raw in inputs.items()):
        raise ValueError('Diagnostic inputs changed')
    verify_cli()
    result['endpoints']=endpoints
    return result
print('EBASE_CATALOG_DIAGNOSTIC:'+json.dumps(collect()),flush=True)
'''


def run_diagnostic(registration):
    require_managed_namespace()
    if registration.get('production_enabled') is not False or registration['roles']['machine'].get('id')!=MACHINE:
        raise ValueError('Fixed nonproduction machine required')
    # Refuse before even a VM start. Existing MCP reservation is not modified.
    if os.path.lexists(CATALOG_RUN): raise FileExistsError('Catalog diagnostic already reserved')
    evidence=Path(tempfile.mkdtemp(prefix='catalog-diagnostic-evidence-',dir=ROOT))
    record=dict(phase='preflight',passed=False,model_executed=False,production_admitted=False)
    atomic_write_json(evidence/'receipt.json',record)
    try:
        with SandboxRuntime(registration,ROOT,capacity=1) as runtime:
            if not same_json(json.loads(_file(ROOT/'sandbox-registry.json',1048576),object_pairs_hook=_pairs),runtime.registration):
                raise ValueError('Locked registration changed')
            inventory(registration)
            boundary=make_boundary_check(IMAGE)
            boundary(runtime,'machine',stage='initial',repo=None,timeout=60)
            with runtime.role('machine') as repo:
                with catalog_diagnostic_network(runtime,repo,timeout=180) as remaining:
                    if remaining<140: raise TimeoutError('Insufficient diagnostic budget')
                    record['phase']='catalog';atomic_write_json(evidence/'receipt.json',record)
                    command=['/usr/bin/python3','-I','-c',PROBE,
                             *[_file(ROOT/(name+'.py'),65536).decode() for name in MODULES],json.dumps(DENY)]
                    log=repo.log_dir/'catalog-diagnostic.log'
                    result=repo.controller.execute(command,cwd='/',log_path=log,timeout=min(140,remaining),
                                                   max_log_bytes=16384,external_stop=repo.external_stop)
                    if type(result.returncode) is not int or result.returncode!=0:
                        raise RuntimeError('Catalog diagnostic guest failed')
                    prefix='EBASE_CATALOG_DIAGNOSTIC:'
                    lines=[s[len(prefix):] for s in _file(log,16384).decode().splitlines() if s.startswith(prefix)]
                    if len(lines)!=1: raise ValueError('One diagnostic receipt required')
                    value=json.loads(lines[0],object_pairs_hook=_pairs)
                    if type(value) is not dict or type(value.get('catalog_verified')) is not bool or value.get('model_executed') is not False:
                        raise ValueError('Non-model diagnostic receipt required')
                    record['catalog']=value
            inventory(registration)
            check_network(runtime,'machine',stage='initial',repo=None,timeout=45)
            record.update(phase='closed',all_vms_stopped=True,network_denied=True,passed=record['catalog']['catalog_verified'])
    finally: atomic_write_json(evidence/'receipt.json',record)
    return dict(evidence=str(evidence),**record)


if __name__=='__main__':
    import sys
    if sys.argv[1:]!=['--once']: raise ValueError('Fixed catalog diagnostic required')
    require_managed_namespace()
    with interruption_cleanup():
        result=run_diagnostic(json.loads(_file(ROOT/'sandbox-registry.json',1048576),object_pairs_hook=_pairs))
    print(json.dumps(result),flush=True)
