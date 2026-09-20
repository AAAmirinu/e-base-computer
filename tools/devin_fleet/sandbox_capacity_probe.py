"""Fixed two/ten idle VMs only. No model/source execution or capacity promotion."""
import fcntl
import json
import signal
from pathlib import Path
import tempfile

from durable import atomic_write_json
from interactive_machine_auth import run
from managed_cli_guard import require_managed_namespace
from sandbox_runtime import SandboxRuntime

ROOT = Path('/home/fleet/controller-validation')
TARGETS = ('machine', 'coordinator')
TEN_TARGETS = TARGETS + ('toolchain', 'kernel', 'stdlib', 'storage', 'services',
                        'applications', 'devtools', 'assurance')
VALIDATION_ID = '84a0fc99-4cbb-4383-a1df-4c22bbe0d2e6'


def available_kib():
    rows = dict(line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
    return int(rows['MemAvailable'].split()[0])


def inventory(registration, running=()):
    rows = json.loads(run('ls', '--json'))['sandboxes']
    if len(rows) != 11:
        raise RuntimeError('Expected eleven VMs')
    for role, entry in registration['roles'].items():
        matches = [r for r in rows if r['name'] == entry['name'] and r['id'] == entry['id']]
        expected = 'running' if role in running else 'stopped'
        if len(matches) != 1 or matches[0]['status'] != expected:
            raise RuntimeError('Unexpected VM identity or state')
    matches = [r for r in rows if r['name'] == 'e-base-validation'
               and r['id'] == VALIDATION_ID]
    if len(matches) != 1 or matches[0]['status'] != 'stopped':
        raise RuntimeError('Exact validation VM must remain stopped')


def main(*, ten=False):
    if type(ten) is not bool:
        raise ValueError('Explicit fixed measurement mode required')
    targets = TEN_TARGETS if ten else TARGETS
    require_managed_namespace()
    def interrupted(number, frame):
        raise KeyboardInterrupt('Capacity measurement interrupted')
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, interrupted)
    registration = json.loads((ROOT/'sandbox-registry.json').read_text())
    # Validate exact identities/capacity shape, but do not promote capacity or enter runtime.
    SandboxRuntime(registration, ROOT/'managed-maintenance', capacity=1)
    with open('/tmp/e-base-devin-fleet-global.lock', 'r') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        inventory(registration)
        free = available_kib()
        if free < 10 * 1024 * 1024:
            raise RuntimeError('Less than 10 GiB available; no VM started')
        for role in targets:
            name = registration['roles'][role]['name']
            rules = json.loads(run('policy', 'ls', name, '--json'))['rules']
            if not any(r.get('scope') == 'sandbox:'+name and r.get('resource_type') == 'network'
                       and r.get('decision') == 'deny' and r.get('status') == 'active'
                       and r.get('resources') == ['**'] for r in rules):
                raise RuntimeError('Network denial required before capacity probe')
        work = Path(tempfile.mkdtemp(prefix='capacity-probe-', dir=ROOT))
        record = {'schema':1, 'targets':list(targets), 'before_available_kib':free,
                  'model_executed':False, 'source_executed':False,
                  'production_capacity_promoted':False, 'phase':'prepared', 'stages':[]}
        path = work/'receipt.json'
        atomic_write_json(path, record)
        print('evidence='+str(work), flush=True)
        attempted = []
        try:
            for role in targets:
                if available_kib() < 6 * 1024 * 1024:
                    raise RuntimeError('Memory headroom fell below reserve')
                attempted.append(role)
                run('exec', registration['roles'][role]['name'], '/usr/bin/true', timeout=45)
                inventory(registration, attempted)
                record['stages'].append({'running_count':len(attempted), 'available_kib':available_kib()})
                atomic_write_json(path, record)
                print('idle_vms='+str(len(attempted)), flush=True)
                if record['stages'][-1]['available_kib'] < 6 * 1024 * 1024:
                    raise RuntimeError('Memory headroom fell below reserve after start')
            record.update(phase='ten_idle_vms_verified' if ten else 'two_idle_vms_verified',
                          during_available_kib=available_kib(), simultaneous_idle_vms=len(targets))
        finally:
            for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
                signal.signal(sig, signal.SIG_IGN)
            errors = []
            for role in reversed(attempted):
                try:
                    run('stop', registration['roles'][role]['name'])
                except Exception:
                    errors.append(role)
            try:
                inventory(registration)
                record['all_vms_stopped'] = True
            except Exception:
                errors.append('inventory')
            record['cleanup_errors'] = errors
            record['after_available_kib'] = available_kib()
            atomic_write_json(path, record)
            print(json.dumps(record), flush=True)
            if errors:
                raise RuntimeError('Capacity cleanup requires inspection')


if __name__ == '__main__':
    import sys
    if sys.argv[1:] not in ([], ['--ten']):
        raise ValueError('Unknown measurement mode')
    main(ten=bool(sys.argv[1:]))
