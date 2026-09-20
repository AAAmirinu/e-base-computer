"""One exclusive closed-network recovery; never resume VMs or clear model fences."""
import json
from pathlib import Path

from candidate_turn_admission import ROOT
from durable import atomic_write_json, _sync_directory
from managed_cli_guard import require_managed_namespace
from model_network_admission import check_network
from network_recovery_record import expected_record
from process_control import GlobalLock
from sandbox_control import LinuxTransport
from sandbox_runtime import SandboxRuntime, ROLES
from sandbox_turn_fence import _directory, _reservation
from turn_validation_result import same_json
from validation_dispatch_receipt import _pairs
from validation_snapshot_dispatch import UUID as VALIDATOR_ID
from validation_snapshot_input import _file


def recover(registration, role, *, transport=None):
    require_managed_namespace()
    registration=json.loads(json.dumps(registration,allow_nan=False))
    if (not isinstance(registration,dict) or role not in ROLES
            or registration.get('production_enabled') is not True
            or not isinstance(registration.get('controller_root'),str)):
        raise ValueError('Explicit production role registration required')
    root=Path(registration['controller_root'])
    if not root.is_absolute() or root.resolve()!=root or ROOT not in root.parents:
        raise ValueError('Canonical dedicated production root required')
    for parent in root.parents:
        _directory(parent)
    _directory(ROOT,private=True)
    _directory(root,private=True)
    selected=LinuxTransport() if transport is None else transport
    # Constructor validates the ten-role registry. Do not enter the runtime:
    # unresolved network recovery is precisely what its restart gate refuses.
    runtime=SandboxRuntime(registration,root,transport=selected)
    with GlobalLock('/tmp/e-base-devin-fleet-global.lock'):
        registry_path=ROOT/'sandbox-registry.json'
        registry_raw=_file(registry_path,65536)
        if not same_json(json.loads(registry_raw,object_pairs_hook=_pairs),registration):
            raise ValueError('Recovery registration changed')
        fences=root/'model-turn-fences'
        _directory(fences,private=True)
        fence_path=fences/(role+'.json')
        fence_raw=_file(fence_path,65536)
        fence=_reservation(fence_raw,role)
        if (fence['migration_epoch']!=registration.get('migration_epoch')
                or fence['sandbox_id']!=registration['roles'][role]['id']):
            raise ValueError('Recovery fence identity mismatch')
        run=Path(fence['run_directory'])
        if root not in run.parents or run.resolve()!=run:
            raise ValueError('Recovery turn must remain under registered root')
        for parent in run.parents:
            _directory(parent)
        _directory(run,private=True)
        window=run/'network-window'
        _directory(window,private=True)
        window_path=window/'network-window.json'
        def window_bytes():
            return _file(window_path,65536)
        window_raw=window_bytes()
        final=expected_record(fence_raw,window_raw,registration,role)
        recovery=window/'recovery'
        recovery.mkdir(mode=0o700)
        _sync_directory(window)
        receipt_path=recovery/'recovery.json'
        pending=dict(schema=1,phase='pending',role=role,automatic_resume=False,
                     model_fence_released=False,stop_removed=False)
        atomic_write_json(receipt_path,pending)
        def command(args):
            completed=selected.control(['/usr/bin/sbx',*args],30)
            if (type(completed.returncode) is not int or completed.returncode!=0
                    or not isinstance(completed.stdout,str) or len(completed.stdout.encode())>1024*1024):
                raise RuntimeError('Bounded recovery control operation failed')
            return completed.stdout
        def stopped():
            value=json.loads(command(['ls','--json']),object_pairs_hook=_pairs)
            rows=value.get('sandboxes') if isinstance(value,dict) else None
            expected={entry['name']:entry['id'] for entry in registration['roles'].values()}
            expected['e-base-validation']=VALIDATOR_ID
            if (not isinstance(rows,list) or len(rows)!=11
                    or any(not isinstance(row,dict) or row.get('status')!='stopped' for row in rows)
                    or {row.get('name') for row in rows}!=set(expected)
                    or any(expected.get(row.get('name'))!=row.get('id') for row in rows)):
                raise ValueError('Exact eleven registered stopped VMs required')
        try:
            stopped()
            command(['policy','deny','network','--sandbox','e-base-'+role,'**'])
            if check_network(runtime,role,stage='initial',repo=None,timeout=45) is not None:
                raise ValueError('Unexpected network verifier result')
            stopped()
            if (_file(registry_path,65536)!=registry_raw or _file(fence_path,65536)!=fence_raw
                    or window_bytes()!=window_raw):
                raise ValueError('Original recovery evidence changed')
            atomic_write_json(receipt_path,final)
            return final
        except BaseException as error:
            pending.update(phase='inspection_required',error_type=type(error).__name__)
            atomic_write_json(receipt_path,pending)
            raise


def main(argv=None):
    import signal
    import sys
    args=sys.argv[1:] if argv is None else argv
    if not isinstance(args,list) or len(args)!=2 or args[0]!='--role' or args[1] not in ROLES:
        raise ValueError('Exactly one fixed role required; no path or identity overrides')
    require_managed_namespace()
    registration=json.loads(_file(ROOT/'sandbox-registry.json',65536),object_pairs_hook=_pairs)
    def interrupted(number,frame):
        raise KeyboardInterrupt('Closed-network recovery interrupted')
    previous={}
    try:
        for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP):
            previous[sig]=signal.signal(sig,interrupted)
        result=recover(registration,args[1])
        print(json.dumps(result),flush=True)
    finally:
        for sig,handler in previous.items():
            signal.signal(sig,handler)


if __name__=='__main__':
    main()
