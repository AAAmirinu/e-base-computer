"""Read-only model network admission. Never creates/removes permission rules."""
import hashlib
import json
import math
import time

from managed_cli_guard import require_managed_namespace
from sandbox_runtime import ROLES
from validation_dispatch_receipt import _pairs

MODEL_HOSTS=frozenset(('api.devin.ai:443','app.devin.ai:443','server.codeium.com:443'))
FEATURE_HOST='unleash.codeium.com:443'
# Observed approval-pending telemetry destination. Never part of the allow set.
DENY_ONLY_HOSTS=frozenset(('o4507463137361920.ingest.us.sentry.io:443',))
KIT_HOSTS=MODEL_HOSTS | frozenset(('windsurf.com:443','unleash.codeium.com:443',
    'cli.devin.ai:443','static.devin.ai:443','archive.ubuntu.com:80',
    'security.ubuntu.com:80','ports.ubuntu.com:80','download.docker.com:443'))
NEGATIVE_HOSTS=('example.com:443','127.0.0.1:443','169.254.169.254:80',
                'api.devin.ai:80','api.devin.ai.example.com:443')


def validate_rules(rows, name, *, model_access, catalog_access=False):
    if type(catalog_access) is not bool or (catalog_access and name!='e-base-machine'):
        raise ValueError('Fixed catalog scope required')
    if type(model_access) is not bool or not isinstance(rows,list) or not 1<=len(rows)<=256:
        raise ValueError('Bounded policy list and explicit access mode required')
    allow=set()
    deny=set()
    normalized=[]
    for row in rows:
        if not isinstance(row,dict):
            raise ValueError('Invalid policy row')
        if row.get('resource_type')!='network':
            continue
        if (row.get('scope')!='sandbox:'+name or row.get('applies_to')!='sandbox:'+name
                or row.get('status')!='active' or row.get('decision') not in ('allow','deny')
                or not isinstance(row.get('resources'),list) or not row['resources']
                or any(not isinstance(host,str) for host in row['resources'])
                or len(set(row['resources']))!=len(row['resources'])):
            raise ValueError('Unknown network scope or rule shape')
        resources=set(row['resources'])
        permitted=KIT_HOSTS if row['decision']=='allow' else KIT_HOSTS|DENY_ONLY_HOSTS
        if not resources<=permitted and not (row['decision']=='deny' and resources=={'**'}):
            raise ValueError('Unreviewed endpoint or wildcard refused')
        (allow if row['decision']=='allow' else deny).update(resources)
        # Kit view IDs can change; preserve all semantic metadata and editable IDs.
        normalized.append({key:value for key,value in row.items()
                           if row.get('editable') is True or key not in ('id','policy_id')})
    if allow!=KIT_HOSTS:
        raise ValueError('Reviewed vendor endpoint set changed')
    if model_access:
        expected=MODEL_HOSTS|{FEATURE_HOST} if catalog_access else MODEL_HOSTS
        if '**' in deny or allow-deny!=expected or not DENY_ONLY_HOSTS<=deny:
            raise ValueError('Exact model-only network access required')
    elif '**' not in deny:
        raise ValueError('Blanket network denial required')
    encoded=json.dumps(sorted(normalized,key=lambda row:json.dumps(row,sort_keys=True)),
                       sort_keys=True,allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def check_network(runtime,role,*,stage,repo,timeout,catalog_access=False,
                  prepared_trial_check=None):
    """Initial/preparation/inspection are closed; model stage is narrowly open.

The lifecycle owner must establish and restore that policy separately. This
checker rejects missing transitions instead of changing policy as a fallback.
"""
    require_managed_namespace()
    trial_catalog = False
    if prepared_trial_check is not None:
        import prepared_candidate_trial_state as trial_state
        trial_catalog = (prepared_trial_check is trial_state.check_runtime_registration
            and role == 'machine' and runtime.root == trial_state.CONTROLLER
            and repo is not None and repo.guest_root == trial_state.trial_guest_root()
            and prepared_trial_check(runtime.registration) is None)
        if not trial_catalog:
            raise ValueError('Exact prepared trial catalog checker required')
    if type(catalog_access) is not bool or (catalog_access and not (
            role == 'machine' and (runtime.registration.get('production_enabled') is False
                                  or trial_catalog))):
        raise ValueError('Catalog-only nonproduction machine required')
    if prepared_trial_check is not None and not catalog_access:
        raise ValueError('Prepared trial checker is catalog-only')
    if role not in ROLES or stage not in ('initial','before_prepare','before_model','before_inspection'):
        raise ValueError('Known role and admission stage required')
    if type(timeout) not in (int,float) or not math.isfinite(timeout) or timeout<=0:
        raise ValueError('Finite remaining time required')
    started=time.monotonic()
    name='e-base-'+role
    if runtime.registration['roles'][role]['name']!=name:
        raise ValueError('Registered role name mismatch')
    model_access=stage=='before_model'
    def query(args,allowed_codes=(0,)):
        seconds=timeout-(time.monotonic()-started)
        if seconds<=0:
            raise TimeoutError('Network admission deadline')
        completed=runtime.transport.control(['/usr/bin/sbx',*args],min(seconds,10))
        if completed.returncode not in allowed_codes or not isinstance(completed.stdout,str):
            raise RuntimeError('Policy query failed')
        if len(completed.stdout.encode())>65536:
            raise ValueError('Policy response exceeded bound')
        return json.loads(completed.stdout,object_pairs_hook=_pairs)
    def rules():
        value=query(['policy','ls',name,'--json'])
        if not isinstance(value,dict) or not isinstance(value.get('rules'),list):
            raise ValueError('Policy list missing')
        return validate_rules(value['rules'],name,model_access=model_access,catalog_access=catalog_access)
    before=rules()
    for host in sorted(KIT_HOSTS|DENY_ONLY_HOSTS)+list(NEGATIVE_HOSTS):
        value=query(['policy','check','network','--sandbox',name,'--json',host],(0,1))
        expected=model_access and host in (MODEL_HOSTS|{FEATURE_HOST} if catalog_access else MODEL_HOSTS)
        if not isinstance(value,dict) or value.get('allowed') is not expected:
            raise ValueError('Effective network policy differs from required scope')
    if rules()!=before:
        raise ValueError('Network policy changed during admission')
    if time.monotonic()-started>=timeout:
        raise TimeoutError('Network admission deadline')


def verify_machine_closed():
    """Fixed maintenance measurement, not production activation or permission."""
    import tempfile
    from durable import atomic_write_json
    from sandbox_capacity_probe import ROOT, inventory
    from sandbox_runtime import SandboxRuntime
    from validation_snapshot_input import _file
    require_managed_namespace()
    registration=json.loads(_file(ROOT/'sandbox-registry.json',65536),object_pairs_hook=_pairs)
    work=ROOT/tempfile.mkdtemp(prefix='model-network-closed-',dir=ROOT)
    record={'schema':1,'phase':'checking','network_changed':False,'model_executed':False,
            'all_vms_stopped':False,'production_admitted':False}
    atomic_write_json(work/'receipt.json',record)
    try:
        with SandboxRuntime(registration,work) as runtime:
            inventory(registration)
            check_network(runtime,'machine',stage='initial',repo=None,timeout=45)
            inventory(registration)
            record.update(phase='closed_policy_verified',all_vms_stopped=True,
                          endpoints_checked=len(KIT_HOSTS|DENY_ONLY_HOSTS)+len(NEGATIVE_HOSTS))
    finally:
        atomic_write_json(work/'receipt.json',record)
    print(json.dumps({'evidence':str(work),**record}),flush=True)


if __name__=='__main__':
    import sys
    if sys.argv[1:]!=['--verify-machine-closed']:
        raise ValueError('Fixed closed-policy action required')
    verify_machine_closed()
