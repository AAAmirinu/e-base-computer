"""Offline auth classification for ten fixed VMs, one at a time; no secrets."""
import fcntl
import json
import signal
import sys
import tempfile

from durable import atomic_write_json
from interactive_machine_auth import run
from managed_cli_guard import require_managed_namespace
from sandbox_auth_probe import PROBE
from sandbox_capacity_probe import ROOT, TEN_TARGETS, inventory
from sandbox_runtime import SandboxRuntime


def classification(raw):
    result = json.loads(raw)
    if (not isinstance(result, dict) or
            set(result) - {'status', 'returncode', 'raw_output_suppressed', 'model_executed'} or
            result.get('status') not in ('not_logged_in', 'unclassified', 'timeout') or
            result.get('raw_output_suppressed') is not True or result.get('model_executed') is not False or
            ('returncode' in result and type(result['returncode']) is not int)):
        raise RuntimeError('Unrecognized auth classification; refusing raw output')
    return result


def main(role=None):
    require_managed_namespace()
    if role is not None and role not in TEN_TARGETS:
        raise ValueError('Known fixed auth inventory role required')
    targets=TEN_TARGETS if role is None else (role,)
    def interrupted(number, frame):
        raise KeyboardInterrupt('Auth inventory interrupted')
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, interrupted)
    registration = json.loads((ROOT/'sandbox-registry.json').read_text())
    SandboxRuntime(registration, ROOT/'managed-maintenance', capacity=1)
    with open('/tmp/e-base-devin-fleet-global.lock', 'r') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        inventory(registration)
        for role in targets:
            name = registration['roles'][role]['name']
            rows = json.loads(run('policy', 'ls', name, '--json'))['rules']
            if not any(r.get('scope') == 'sandbox:'+name and r.get('resource_type') == 'network'
                       and r.get('decision') == 'deny' and r.get('status') == 'active'
                       and r.get('resources') == ['**'] for r in rows):
                raise RuntimeError('All role networks must remain denied')
        work = ROOT/tempfile.mkdtemp(prefix='auth-inventory-', dir=ROOT)
        record = {'schema':1, 'roles':{}, 'model_executed':False,
                  'raw_output_suppressed':True, 'credentials_copied':False,
                  'phase':'checking', 'all_vms_stopped':False}
        path = work/'receipt.json'
        atomic_write_json(path, record)
        print('evidence='+str(work), flush=True)
        try:
            for role in targets:
                name = registration['roles'][role]['name']
                try:
                    result = classification(run('exec', name, '/usr/bin/python3', '-I', '-c', PROBE, timeout=45))
                    record['roles'][role] = result
                finally:
                    previous = {sig:signal.signal(sig, signal.SIG_IGN)
                                for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
                    try:
                        run('stop', name)
                        inventory(registration)
                    finally:
                        for sig, handler in previous.items():
                            signal.signal(sig, handler)
                atomic_write_json(path, record)
                print(role+': '+result['status'], flush=True)
            record['phase'] = 'complete'
        finally:
            try:
                inventory(registration)
                record['all_vms_stopped'] = True
            finally:
                atomic_write_json(path, record)
        print(json.dumps(record), flush=True)


if __name__ == '__main__':
    if sys.argv[1:]==[]:main()
    elif len(sys.argv[1:])==2 and sys.argv[1]=='--role':main(sys.argv[2])
    else:raise ValueError('Fixed auth inventory action required')
