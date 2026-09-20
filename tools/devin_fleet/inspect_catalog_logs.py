"""Closed-network inspection of existing logs; no CLI invocation or replay."""
import json
import tempfile
from pathlib import Path
from catalog_log_summary import PROBE,PATTERNS
from durable import atomic_write_json
from managed_cli_guard import require_managed_namespace
from mcp_probe_entry import interruption_cleanup
from mcp_maintenance_network import IMAGE
from mcp_maintenance_restart import MACHINE
from model_network_admission import check_network
from observed_boundary_admission import make_boundary_check
from sandbox_capacity_probe import ROOT,inventory
from sandbox_runtime import SandboxRuntime
from validation_dispatch_receipt import _pairs
from validation_snapshot_input import _file


def main(*,compatible=False):
    if type(compatible) is not bool:raise ValueError('Fixed log inspection profile required')
    patterns=PATTERNS
    source=_file(ROOT/'catalog_log_summary.py',16384).decode()
    if compatible:
        from compatible_log_summary import compose,PATTERNS as patterns
        source=compose(source)
    require_managed_namespace()
    registration=json.loads(_file(ROOT/'sandbox-registry.json',1048576),object_pairs_hook=_pairs)
    if registration.get('production_enabled') is not False or registration['roles']['machine'].get('id')!=MACHINE:
        raise ValueError('Fixed maintenance machine required')
    work=Path(tempfile.mkdtemp(prefix='compatible-log-inspection-' if compatible else 'catalog-log-inspection-',dir=ROOT))
    record=dict(phase='checking',network_changed=False,model_executed=False)
    try:
        with interruption_cleanup(),SandboxRuntime(registration,ROOT,capacity=1) as runtime:
            inventory(registration)
            check_network(runtime,'machine',stage='initial',repo=None,timeout=45)
            boundary=make_boundary_check(IMAGE)
            boundary(runtime,'machine',stage='initial',repo=None,timeout=60)
            with runtime.role('machine') as repo:
                boundary(runtime,'machine',stage='before_inspection',repo=repo,timeout=60)
                check_network(runtime,'machine',stage='before_inspection',repo=repo,timeout=45)
                result=repo.controller.execute(['/usr/bin/python3','-I','-c',PROBE,
                    source],cwd='/',log_path=work/'summary.log',
                    timeout=20,max_log_bytes=8192,external_stop=repo.external_stop)
                if result.returncode!=0:raise RuntimeError('Offline log inspection failed')
                prefix='EBASE_LOG_SUMMARY:'
                rows=[s[len(prefix):] for s in _file(work/'summary.log',8192).decode().splitlines() if s.startswith(prefix)]
                if len(rows)!=1:raise ValueError('One finite summary required')
                value=json.loads(rows[0],object_pairs_hook=_pairs)
                flags={'attempt_bound':False,'raw_log_exported':False,'credential_store_accessed':False,
                       'secrets_extracted':False,'cli_executed':False,'model_executed':False,'read_complete':True}
                if (type(value) is not dict or set(value)!=set(flags)|{'candidate_count','categories'}
                        or any(value[k] is not v for k,v in flags.items())
                        or type(value['candidate_count']) is not int or not 0<=value['candidate_count']<=8
                        or type(value['categories']) is not dict or set(value['categories'])!=set(patterns)
                        or any(type(n) is not int or not 0<=n<=1000 for n in value['categories'].values())):
                    raise ValueError('Invalid finite log summary')
                record['summary']=value
            inventory(registration)
            check_network(runtime,'machine',stage='initial',repo=None,timeout=45)
            record.update(phase='closed',all_vms_stopped=True,network_denied=True)
    finally:atomic_write_json(work/'receipt.json',record)
    print(json.dumps(dict(evidence=str(work),**record)),flush=True)


if __name__=='__main__':
    import sys
    if sys.argv[1:] not in ([],['--compatible']):raise ValueError('Fixed log profile required')
    main(compatible=sys.argv[1:]==['--compatible'])
