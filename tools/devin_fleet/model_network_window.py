"""Bounded model-only network window with durable, non-secret recovery journal.

No standalone CLI. Caller owns the runtime lock, signal handling and VM lease.
SIGKILL/power loss cannot run finally: retained journals require closed-network
recovery before any subsequent VM resume. This module does not authorize it.
"""
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import time

from durable import atomic_write_json, _sync_directory
from managed_cli_guard import require_managed_namespace
from model_network_admission import KIT_HOSTS, MODEL_HOSTS, DENY_ONLY_HOSTS, FEATURE_HOST, check_network, validate_rules
from process_control import global_lock_held
from sandbox_repository import GuestRepository
from sandbox_turn_fence import _directory, _reservation
from validation_dispatch_receipt import _pairs
from validation_snapshot_input import _file

CATALOG_WINDOW=Path('/home/fleet/controller-validation/catalog-diagnostic-v5/network-window')
MCP_WINDOW=Path('/home/fleet/controller-validation/mcp-live-v2/network-window')
DISCOVERY_WINDOW=Path('/home/fleet/controller-validation/mcp-discovery-live-v1/network-window')
WILDCARD_WINDOW=Path('/home/fleet/controller-validation/mcp-wildcard-live-v1/network-window')
CONTROL_WINDOW=Path('/home/fleet/controller-validation/mcp-echo-control-live-v2/network-window')
COMPATIBLE_CONTROL_WINDOW=Path('/home/fleet/controller-validation/mcp-echo-compatible-live-v1/network-window')
PARAMS_CONTROL_WINDOW=Path('/home/fleet/controller-validation/mcp-echo-params-live-v1/network-window')


@contextmanager
def model_network_window(runtime,role,repo,directory,*,timeout):
    require_managed_namespace()
    if type(timeout) not in (int,float) or not math.isfinite(timeout) or timeout<=0:
        raise ValueError('Finite model network window timeout required')
    name='e-base-'+role
    entry=runtime.registration['roles'][role]
    active=runtime._active.get(role)
    if (runtime.registration.get('production_enabled') is not True
            or not runtime._entered or runtime._failed
            or not global_lock_held('/tmp/e-base-devin-fleet-global.lock')
            or entry['name']!=name or not isinstance(repo,GuestRepository)
            or active is None or repo.controller is not active[1]
            or repo.controller.fenced or repo.controller.sandbox_id!=entry['id']
            or repo.external_stop!=runtime.stop_path):
        raise ValueError('Exact active production lease and lock required')
    directory=Path(directory)
    if not directory.is_absolute() or directory.resolve()!=directory or runtime.root not in directory.parents:
        raise ValueError('New window directory under private controller root required')
    for parent in directory.parents:
        _directory(parent,private=parent==runtime.root)
    # Restart inspection follows the durable role fence, not caller-selected
    # directories. Refuse any window it could otherwise fail to discover.
    if runtime.registration.get('controller_root') != str(runtime.root):
        raise ValueError('Registered controller root required')
    fences=runtime.root/'model-turn-fences'
    _directory(fences,private=True)
    reservation=_reservation(_file(fences/(role+'.json'),65536),role)
    run=Path(reservation['run_directory'])
    if (reservation['migration_epoch']!=runtime.registration.get('migration_epoch')
            or reservation['sandbox_id']!=entry['id']
            or runtime.root not in run.parents or run.resolve()!=run
            or directory!=run/'network-window'):
        raise ValueError('Network window must match the exact unresolved role turn')
    _directory(run,private=True)
    with _policy_window(runtime,role,repo,directory,timeout=timeout):
        yield


@contextmanager
def prepared_trial_catalog_window(runtime, role, repo, directory, *, timeout):
    """Exact prepared-trial catalog window; feature access is temporary."""
    import prepared_candidate_trial_state as trial_state
    if (role != 'machine' or repo.guest_root != trial_state.trial_guest_root()
            or runtime.root != trial_state.CONTROLLER
            or trial_state.check_runtime_registration(runtime.registration) is not None):
        raise ValueError('Exact prepared trial catalog lease required')
    directory = Path(directory)
    fences = runtime.root / 'model-turn-fences'
    reservation = _reservation(_file(fences / (role + '.json'), 65536), role)
    run = Path(reservation['run_directory'])
    if (reservation['migration_epoch'] != runtime.registration.get('migration_epoch')
            or reservation['sandbox_id'] != runtime.registration['roles'][role]['id']
            or directory != run / 'network-window'):
        raise ValueError('Prepared trial catalog window must match turn fence')
    with _policy_window(runtime, role, repo, directory, timeout=timeout,
                        catalog_access=True, prepared_trial=True):
        yield


@contextmanager
def _policy_window(runtime,role,repo,directory,*,timeout,catalog_access=False,
                   prepared_trial=False):
    """Internal mutation engine; only callers with checked ownership may use it.

    It is not an admission API. Production and fixed maintenance wrappers must
    establish their own durable, restart-visible reservation before entry.
    """
    name='e-base-'+role
    entry=runtime.registration['roles'][role]
    require_managed_namespace()
    diagnostic = (runtime.registration.get('production_enabled') is False and role == 'machine'
        and directory in (CATALOG_WINDOW,MCP_WINDOW,DISCOVERY_WINDOW,WILDCARD_WINDOW,
                          CONTROL_WINDOW,COMPATIBLE_CONTROL_WINDOW,PARAMS_CONTROL_WINDOW))
    if (type(catalog_access) is not bool or type(prepared_trial) is not bool
            or prepared_trial and not catalog_access
            or catalog_access and not (diagnostic or prepared_trial)):
        raise ValueError('Fixed nonproduction diagnostic window required')
    if prepared_trial:
        import prepared_candidate_trial_state as trial_state
        if (role != 'machine' or runtime.root != trial_state.CONTROLLER
                or trial_state.check_runtime_registration(runtime.registration) is not None
                or repo.guest_root != trial_state.trial_guest_root()):
            raise ValueError('Exact prepared trial policy window required')
    active=runtime._active.get(role)
    if (not runtime._entered or runtime._failed or not global_lock_held('/tmp/e-base-devin-fleet-global.lock')
            or not isinstance(repo,GuestRepository) or active is None or active[1] is not repo.controller
            or repo.controller.fenced or repo.controller.sandbox_id!=entry['id']
            or entry['name']!=name or repo.external_stop!=runtime.stop_path
            or type(timeout) not in (int,float) or not math.isfinite(timeout) or timeout<=0
            or not directory.is_absolute() or directory.resolve()!=directory or runtime.root not in directory.parents):
        raise ValueError('Checked active lease required for policy mutation')
    directory.mkdir(mode=0o700)
    _sync_directory(directory.parent)
    record={'schema':1,'role':role,'sandbox_id':entry['id'],'phase':'prepared',
            'network_denied_after':False,'automatic_resume':False,'created_deny_ids':[]}
    def save(phase):
        record['phase']=phase
        atomic_write_json(directory/'network-window.json',record)
    save('prepared')
    started=time.monotonic()
    def remaining():
        seconds=timeout-(time.monotonic()-started)
        if seconds<=0 or os.path.lexists(runtime.stop_path):
            raise RuntimeError('Network window deadline or STOP')
        return seconds
    def command(args,*,cleanup=False):
        result=runtime.transport.control(['/usr/bin/sbx',*args],10 if cleanup else min(remaining(),10))
        if type(result.returncode) is not int or result.returncode!=0:
            raise RuntimeError('Network policy operation failed')
        if not isinstance(result.stdout,str) or len(result.stdout.encode())>65536:
            raise ValueError('Bounded policy operation output required')
        return result.stdout
    def rules():
        value=json.loads(command(['policy','ls',name,'--json']),object_pairs_hook=_pairs)
        if not isinstance(value,dict) or not isinstance(value.get('rules'),list):
            raise ValueError('Network policy list missing')
        validate_rules(value['rules'],name,model_access=False)
        return value['rules']
    def scoped(row):
        return (row.get('resource_type')=='network' and row.get('decision')=='deny'
                and row.get('status')=='active' and row.get('editable') is True
                and row.get('scope')=='sandbox:'+name and row.get('applies_to')=='sandbox:'+name)
    try:
        check_network(runtime,role,stage='before_prepare',repo=repo,timeout=remaining())
        before=rules()
        blanket=[row for row in before if scoped(row) and row.get('resources')==['**']]
        if len(blanket)!=1 or not isinstance(blanket[0].get('id'),str):
            raise ValueError('Unique editable blanket denial required')
        original_id=blanket[0]['id']
        record['original_deny_id']=original_id
        save('adding_restrictions')
        blocked=(KIT_HOSTS-MODEL_HOSTS)|DENY_ONLY_HOSTS
        if catalog_access: blocked=blocked-{FEATURE_HOST}
        command(['policy','deny','network','--sandbox',name,','.join(sorted(blocked))])
        after=rules()
        old={r['id']:r for r in before if r.get('editable') is True}
        current={r['id']:r for r in after if r.get('editable') is True}
        if len(current)!=sum(r.get('editable') is True for r in after) or any(current.get(k)!=v for k,v in old.items()):
            raise ValueError('Existing editable policy changed')
        created=[r for k,r in current.items() if k not in old]
        if (any(not scoped(r) or not isinstance(r.get('resources'),list)
                              or not r['resources'] or not set(r['resources'])<=blocked for r in created)
                or {h for r in current.values() if scoped(r) and isinstance(r.get('resources'),list)
                    and set(r['resources'])<=blocked for h in r['resources']}!=blocked):
            raise ValueError('Exact new restrictions not confirmed')
        # Immutable vendor-rule semantics must also remain unchanged.
        def fixed(rows):
            return sorted(json.dumps({k:v for k,v in r.items() if k not in ('id','policy_id')},sort_keys=True)
                          for r in rows if r.get('editable') is not True)
        if fixed(before)!=fixed(after):
            raise ValueError('Vendor policy changed')
        record['created_deny_ids']=[r['id'] for r in created]
        save('opening')  # Durable before the operation with an uncertain outcome.
        if catalog_access:
            feature_denies=[r for r in after if r.get('decision')=='deny' and FEATURE_HOST in r.get('resources',[])]
            if any(not scoped(r) or r['resources']!=[FEATURE_HOST] for r in feature_denies):
                raise ValueError('Only standalone owned feature denial may be removed')
            for row in feature_denies:
                command(['policy','rm','network','--sandbox',name,'--id',row['id']])
        command(['policy','rm','network','--sandbox',name,'--id',original_id])
        if catalog_access:
            trial_check = None
            if prepared_trial:
                import prepared_candidate_trial_state as trial_state
                trial_check = trial_state.check_runtime_registration
            check_network(runtime,role,stage='before_model',repo=repo,timeout=remaining(),
                          catalog_access=True, prepared_trial_check=trial_check)
        else:
            check_network(runtime,role,stage='before_model',repo=repo,timeout=remaining())
        save('open')
        yield
    finally:
        # Always add denial, including a timed-out rm with an unknown outcome.
        # Leave restrictive temporary rules in place; never broaden during cleanup.
        try:
            command(['policy','deny','network','--sandbox',name,'**'],cleanup=True)
            if catalog_access:
                command(['policy','deny','network','--sandbox',name,FEATURE_HOST],cleanup=True)
            check_network(runtime,role,stage='before_inspection',repo=repo,timeout=45)
            record['network_denied_after']=True
            save('closed')
        except BaseException:
            try:
                save('inspection_required')
            finally:
                repo.controller.stop()
            raise
def close_catalog_access(runtime, role, repo, directory, *, timeout):
    """Trial transition: deny the feature host before model execution."""
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('Finite catalog-close deadline required')
    directory = Path(directory)
    if runtime.root not in directory.parents or directory.resolve() != directory:
        raise ValueError('Catalog-close evidence must remain under runtime root')
    import prepared_candidate_trial_state as trial_state
    check_network(runtime, role, stage='before_model', repo=repo,
                  timeout=timeout, catalog_access=True,
                  prepared_trial_check=trial_state.check_runtime_registration)
    name = runtime.registration['roles'][role]['name']
    result = runtime.transport.control(['/usr/bin/sbx', 'policy', 'deny', 'network',
        '--sandbox', name, FEATURE_HOST], min(timeout, 10))
    if result.returncode != 0:
        raise RuntimeError('Feature-host denial failed')
    check_network(runtime, role, stage='before_model', repo=repo, timeout=timeout)
    atomic_write_json(directory / 'catalog-close.json', {'schema': 1, 'phase': 'closed',
        'role': role, 'feature_host_denied': True, 'model_access_only': True})
