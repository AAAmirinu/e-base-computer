"""Fixed deny-only maintenance; never starts a guest or opens network."""
import json
import tempfile

from durable import atomic_write_json
from managed_cli_guard import require_managed_namespace
from mcp_maintenance_restart import MACHINE
from model_network_admission import DENY_ONLY_HOSTS, check_network, validate_rules
from process_control import global_lock_held
from sandbox_capacity_probe import ROOT, inventory
from sandbox_runtime import SandboxRuntime
from validation_dispatch_receipt import _pairs
from validation_snapshot_input import _file


def apply_closed(runtime, *, before_add):
    require_managed_namespace()
    if (not runtime._entered or runtime._failed or runtime._active
            or runtime.registration.get('production_enabled') is not False
            or runtime.registration['roles']['machine'].get('name')!='e-base-machine'
            or runtime.registration['roles']['machine'].get('id')!=MACHINE
            or not callable(before_add)
            or not global_lock_held('/tmp/e-base-devin-fleet-global.lock')):
        raise ValueError('Stopped fixed maintenance runtime and lock required')
    def command(args):
        result=runtime.transport.control(['/usr/bin/sbx',*args],10)
        if type(result.returncode) is not int or result.returncode!=0:
            raise RuntimeError('Policy operation failed; do not retry automatically')
        if type(result.stdout) is not str or len(result.stdout.encode())>65536:
            raise ValueError('Bounded policy response required')
        return result.stdout
    def rows():
        result=json.loads(command(['policy','ls','e-base-machine','--json']),object_pairs_hook=_pairs)
        if type(result) is not dict or type(result.get('rules')) is not list:
            raise ValueError('Policy list required')
        validate_rules(result['rules'],'e-base-machine',model_access=False)
        return result['rules']
    inventory(runtime.registration)
    check_network(runtime,'machine',stage='initial',repo=None,timeout=45)
    before=rows()
    denied={h for row in before if row.get('resource_type')=='network' and row.get('decision')=='deny'
            for h in row['resources']}
    if DENY_ONLY_HOSTS<=denied:
        changed=False
    else:
        before_add()
        command(['policy','deny','network','--sandbox','e-base-machine',','.join(sorted(DENY_ONLY_HOSTS))])
        changed=True
    after=rows()
    def editable(values):
        result={r['id']:r for r in values if r.get('editable') is True}
        if len(result)!=sum(r.get('editable') is True for r in values):
            raise ValueError('Duplicate editable rule identity')
        return result
    old,new=editable(before),editable(after)
    if any(new.get(k)!=v for k,v in old.items()):
        raise ValueError('Existing editable policy changed')
    def fixed(values):
        return sorted(json.dumps({k:v for k,v in r.items() if k not in ('id','policy_id')},sort_keys=True)
                      for r in values if r.get('editable') is not True)
    if fixed(before)!=fixed(after): raise ValueError('Vendor policy changed')
    added=[r for k,r in new.items() if k not in old]
    if changed and (not added or any(r.get('resource_type')!='network' or r.get('decision')!='deny'
                                   or not set(r['resources'])<=DENY_ONLY_HOSTS for r in added)
                    or {h for r in added for h in r['resources']}!=DENY_ONLY_HOSTS):
        raise ValueError('Exact telemetry denial not confirmed')
    if not changed and added: raise ValueError('Unexpected policy addition')
    check_network(runtime,'machine',stage='initial',repo=None,timeout=45)
    inventory(runtime.registration)
    return dict(deny_added=changed,network_denied=True,all_vms_stopped=True,
                model_executed=False,production_admitted=False)


def main():
    import sys
    if sys.argv[1:]!=['--closed-only']: raise ValueError('Fixed closed-only action required')
    require_managed_namespace()
    registration=json.loads(_file(ROOT/'sandbox-registry.json',65536),object_pairs_hook=_pairs)
    evidence=ROOT/tempfile.mkdtemp(prefix='telemetry-deny-',dir=ROOT)
    record=dict(phase='checking',passed=False,model_executed=False,production_admitted=False)
    atomic_write_json(evidence/'receipt.json',record)
    def before_add():
        record.update(phase='adding_denial',automatic_retry=False)
        atomic_write_json(evidence/'receipt.json',record)
    try:
        with SandboxRuntime(registration,ROOT,capacity=1) as runtime:
            record.update(apply_closed(runtime,before_add=before_add),phase='closed_denial_verified',passed=True)
    except BaseException:
        record.update(phase='inspection_required',passed=False,automatic_retry=False)
        raise
    finally:
        atomic_write_json(evidence/'receipt.json',record)
    print(json.dumps(dict(evidence=str(evidence),**record)),flush=True)


if __name__=='__main__': main()
