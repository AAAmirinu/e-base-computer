"""User-operated, non-recorded login. Only machine auth HTTPS is temporary.

Invoke in a real terminal inside the managed namespaces. Never capture this
program's terminal output. No credentials are read by this controller.
"""
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile

from durable import atomic_write_json
from managed_cli_guard import require_managed_namespace

NAME = 'e-base-machine'
UUID = '40e32a36-d565-4853-a841-fa3bea9ac648'
LOGIN_TARGETS = {
    'machine': UUID,
    'coordinator': '90cd1b4d-d8b6-4199-9e86-ddf1e59ba552',
    'toolchain': 'af53960e-7353-4c53-8d1d-9b4ead8fefb0',
    'kernel': 'ee03f652-9756-467c-9523-0764b1f42d6a',
    'stdlib': '53309df1-bbf5-4aa7-9614-b6159d607d6c',
    'storage': 'd401d8a1-edd4-460f-ba01-2e2a20fd46f3',
    'services': 'af3020c9-4112-41a6-bfba-baa866dea34e',
    'applications': '4cacfd64-5b54-4704-b636-dd101e35dd5b',
    'devtools': '16d99bbc-2821-48e5-97fa-02084f75c11e',
    'assurance': '7e7b1e74-d779-452d-9287-1101ab3ea19e',
}


def select_login_target(role):
    """One target per child process; no caller-provided UUID or command."""
    global NAME, UUID
    if not isinstance(role, str) or role not in LOGIN_TARGETS:
        raise ValueError('Unknown fixed login role')
    NAME, UUID = 'e-base-'+role, LOGIN_TARGETS[role]

HOSTS = {'api.devin.ai:443', 'app.devin.ai:443', 'server.codeium.com:443'}
CLI = ['/bin/sh', '/home/fleet/sbx-headless.sh']
CATALOG_PROBE = r'''
import json, subprocess
try:
    result = subprocess.run(['/home/agent/.local/bin/devin-cli', 'models', 'list', '--format', 'json'],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    if result.returncode:
        print(json.dumps({'catalog_status':'command_failed','returncode':result.returncode}))
    else:
        catalog = json.loads(result.stdout)
        variants = [v for f in catalog['families'] for v in f['variants']]
        selected = [{k:v.get(k) for k in ('model_uid','cost_tier')} for v in variants
                    if str(v.get('model_uid','')).startswith('swe-2')]
        print(json.dumps({'catalog_status':'parsed','swe2_variants':selected,'model_executed':False}))
except Exception as error:
    print(json.dumps({'catalog_status':'failed','error_type':type(error).__name__}))
'''


def run(*args, allowed=(0,), timeout=30):
    result = subprocess.Popen(CLI + list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, start_new_session=True)
    try:
        output, _ = result.communicate(timeout=timeout)
    except BaseException:
        try:
            os.killpg(result.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        result.communicate(timeout=5)
        raise
    if result.returncode not in allowed:
        raise RuntimeError('Auth maintenance command failed: ' + args[0])
    return output


def rules():
    return json.loads(run('policy', 'ls', NAME, '--json'))['rules']


def allowed(host):
    return json.loads(run('policy', 'check', 'network', '--sandbox', NAME, '--json', host,
                          allowed=(0, 1)))['allowed']


def stopped():
    rows = json.loads(run('ls', '--json'))['sandboxes']
    matching = [row for row in rows if row['name'] == NAME and row['id'] == UUID]
    if len(rows) != 11 or len(matching) != 1 or any(row['status'] != 'stopped' for row in rows):
        raise RuntimeError('Eleven stopped VMs and exact machine UUID required')


def scoped_deny(row):
    return (row.get('resource_type') == 'network' and row.get('decision') == 'deny'
            and row.get('status') == 'active' and row.get('editable') is True
            and row.get('scope') == 'sandbox:'+NAME
            and row.get('applies_to') == 'sandbox:'+NAME)


def recover_machine_denial():
    """Caller holds the global lock. Restore denial, never reopen or remove rules."""
    stopped()
    before = rules()
    present = any(scoped_deny(r) and r.get('resources') == ['**'] for r in before)
    if not present:
        run('policy', 'deny', 'network', '--sandbox', NAME, '**')
    after = rules()
    if not any(scoped_deny(r) and r.get('resources') == ['**'] for r in after):
        raise RuntimeError('Recovery failed to establish blanket denial')
    if any(allowed(h) is not False for h in HOSTS | {'example.com:443'}):
        raise RuntimeError('Recovered network policy check failed')
    stopped()
    return {'schema': 1, 'sandbox_id': UUID, 'network_denied_after': True,
            'all_vms_stopped': True, 'added_blanket_deny': not present,
            'model_executed': False, 'rules_removed': False, 'resume_available': False}


def restriction_ids(before, after, blocked):
    """Own only new editable restrictions; kit view IDs are not stable identities."""
    def fixed(rows):
        return sorted(json.dumps({k: v for k, v in r.items() if k not in ('id', 'policy_id')},
                                 sort_keys=True) for r in rows if r.get('editable') is not True)
    old = {r['id']: r for r in before if r.get('editable') is True}
    current = {r['id']: r for r in after if r.get('editable') is True}
    if len(current) != sum(r.get('editable') is True for r in after):
        raise RuntimeError('Duplicate editable rule identity')
    if fixed(before) != fixed(after) or any(current.get(key) != row for key, row in old.items()):
        raise RuntimeError('Existing policy changed during restriction setup')
    created = [r for key, r in current.items() if key not in old]
    expected = set(blocked)
    def matching(row):
        resources = row.get('resources')
        return (scoped_deny(row) and isinstance(resources, list) and bool(resources)
                and set(resources) <= expected)
    if any(not matching(r) for r in created):
        raise RuntimeError('Unexpected new editable policy')
    coverage = {host for r in current.values() if matching(r) for host in r['resources']}
    if coverage != expected:
        raise RuntimeError('Temporary restriction coverage incomplete')
    return [r['id'] for r in created]


def main(*, check_policy=False, catalog_check=False, model_smoke=False, smoke_evidence=False, file_tool_probe=False, file_probe_evidence=False, shell_denial_probe=False, shell_probe_evidence=False, eword_edit=False, eword_evidence=False):
    if (file_tool_probe or shell_denial_probe or eword_edit or eword_evidence) and NAME != 'e-base-machine':
        raise RuntimeError('File probe is limited to machine')
    if not (check_policy or catalog_check or model_smoke or smoke_evidence or file_tool_probe or file_probe_evidence or shell_denial_probe or shell_probe_evidence or eword_edit or eword_evidence) and not all(os.isatty(fd) for fd in (0, 1, 2)):
        raise RuntimeError('Private user-operated terminal required; no pipes/log capture')
    require_managed_namespace()
    edit_source = None
    if eword_edit:
        # Validate the pinned public baseline before permitting any network operation.
        from validation_snapshot_input import load_snapshot
        _, blobs, manifest = load_snapshot(
            '/home/fleet/controller-validation/eword-baseline-xxlcbs8p',
            '47810d95844b90f04844cf85ad8a42a62f91e4c0157beeb9a19836dc12c4f2ea')
        entries = [f for f in manifest['files'] if f['path'] == 'src/ecomputer.py']
        if len(entries) != 1:
            raise RuntimeError('Unique public source required')
        edit_source = blobs[entries[0]['sha256']].decode('utf-8')
    def interrupted(number, frame):
        raise KeyboardInterrupt('Authentication cancelled')
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, interrupted)
    with open('/tmp/e-base-devin-fleet-global.lock', 'r') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        stopped()
        original = rules()
        network = [r for r in original if r['resource_type'] == 'network' and r['status'] == 'active']
        denies = [r for r in network if r['decision'] == 'deny' and r['resources'] == ['**']
                  and r['scope'] == 'sandbox:'+NAME and r['editable'] is True]
        if len(denies) != 1:
            raise RuntimeError('Exact scoped deny baseline required')
        existing_allow = set(h for r in network if r['decision'] == 'allow' for h in r['resources'])
        if not HOSTS <= existing_allow or any('*' in h for h in existing_allow):
            raise RuntimeError('Unexpected vendor policy; refusing broad access')
        blocked = sorted(existing_allow - HOSTS)
        work = Path(tempfile.mkdtemp(prefix='interactive-auth-', dir='/home/fleet/controller-validation'))
        record = {'schema': 1, 'phase': 'prepared', 'sandbox_id': UUID, 'sandbox_name': NAME,
                  'auth_hosts': sorted(HOSTS), 'original_deny_id': denies[0]['id'],
                  'model_executed': False, 'terminal_recorded': False}
        def save():
            atomic_write_json(work/'receipt.json', record)
        save()
        if eword_edit:
            print('Bounded public-source file edit; no candidate code execution.', flush=True)
        elif shell_denial_probe:
            print('Single harmless shell-denial probe; deny policy remains unchanged.', flush=True)
        elif file_tool_probe:
            print('Single synthetic file-tool probe; no project input or code execution.', flush=True)
        elif model_smoke:
            print('Single fixed SWE-2 maintenance smoke; no project tools permitted.', flush=True)
        elif check_policy or catalog_check or smoke_evidence or file_probe_evidence or shell_probe_evidence or eword_evidence:
            print('Maintenance verification only; no login or model inference.', flush=True)
        else:
            print('Private authentication terminal. Do not paste tokens into chat.', flush=True)
            print('Target: ' + NAME, flush=True)
            print('Time limit: 10 minutes. Ctrl+C cancels and restores network denial.', flush=True)
        print('Evidence (no credentials): ' + str(work), flush=True)
        temporary_ids = []
        changed = False
        try:
            if eword_evidence:
                smoke_source = Path(__file__).with_name('machine_cli_smoke.py').read_text()
                helper = Path(__file__).with_name('machine_eword_edit.py').read_text()
                source = ('import types\nsmoke=types.ModuleType("smoke_library")\n'
                          'exec(' + repr(smoke_source) + ', smoke.__dict__)\n'
                          + helper + '\ninspect_saved(smoke)\n')
                record['eword_evidence'] = json.loads(run('exec', NAME, '/usr/bin/python3', '-I', '-c', source))
                print(json.dumps(record['eword_evidence']), flush=True)
                return
            if smoke_evidence or file_probe_evidence or shell_probe_evidence:
                source = Path(__file__).with_name('machine_cli_smoke.py').read_text()
                inspect_arg = ('--inspect-shell-probe' if shell_probe_evidence else
                               '--inspect-file-probe' if file_probe_evidence else '--inspect')
                record['smoke_evidence'] = json.loads(run('exec', NAME, '/usr/bin/python3', '-I', '-c', source, inspect_arg))
                print(json.dumps(record['smoke_evidence']), flush=True)
                return
            if blocked:
                run('policy', 'deny', 'network', '--sandbox', NAME, ','.join(blocked))
                temporary_ids = restriction_ids(original, rules(), blocked)
            record.update(phase='restricting_for_auth', temporary_deny_ids=temporary_ids)
            save()
            if check_policy:
                record['policy_check_passed'] = True
                return
            changed = True
            run('policy', 'rm', 'network', '--sandbox', NAME, '--id', denies[0]['id'])
            if (any(allowed(h) is not True for h in HOSTS) or
                    any(allowed(h) is not False for h in blocked + ['example.com:443'])):
                raise RuntimeError('Auth-only network scope not established')
            if eword_edit:
                import base64
                import hashlib
                smoke_source = Path(__file__).with_name('machine_cli_smoke.py').read_text()
                helper = Path(__file__).with_name('machine_eword_edit.py').read_text()
                source = ('import types\nsmoke=types.ModuleType("smoke_library")\n'
                          'exec(' + repr(smoke_source) + ', smoke.__dict__)\n'
                          + helper + '\nmain(' + repr(edit_source) + ', smoke)\n')
                record.update(phase='eword_edit_attempt', model_executed='attempted')
                save()
                result = json.loads(run('exec', NAME, '/usr/bin/python3', '-I', '-c', source, timeout=230))
                candidate = result.pop('candidate_base64', None)
                if candidate is not None:
                    if not isinstance(candidate, str) or len(candidate) > 44000 or result.get('passed') is not True:
                        raise ValueError('Invalid candidate envelope')
                    raw = base64.b64decode(candidate, validate=True)
                    if (not 0 < len(raw) <= 32768 or b'\x00' in raw or
                            hashlib.sha256(raw).hexdigest() != result.get('candidate_sha256') or
                            hashlib.sha256(edit_source.encode()).hexdigest() != result.get('input_sha256')):
                        raise ValueError('Candidate binding failed')
                    raw.decode('utf-8')
                    with (work/'ecomputer.py.candidate').open('xb') as handle:
                        handle.write(raw)
                        handle.flush()
                        os.fsync(handle.fileno())
                    result['candidate_path'] = str(work/'ecomputer.py.candidate')
                elif result.get('passed') is True:
                    raise ValueError('Missing candidate')
                record['eword_edit'] = result
                save()
                print(json.dumps(result), flush=True)
                return
            if model_smoke or file_tool_probe or shell_denial_probe:
                record.update(phase='maintenance_smoke_attempt', model_executed='attempted')
                save()
                source = Path(__file__).with_name('machine_cli_smoke.py').read_text()
                probe_args = (['--shell-denial-probe'] if shell_denial_probe else
                              ['--file-tool-probe'] if file_tool_probe else [])
                record['smoke'] = json.loads(run('exec', NAME, '/usr/bin/python3', '-I', '-c', source, *probe_args, timeout=150))
                save()
                print(json.dumps(record['smoke']), flush=True)
                return
            if catalog_check:
                record['catalog'] = json.loads(run('exec', NAME, '/usr/bin/python3', '-I', '-c', CATALOG_PROBE))
                save()
                print(json.dumps(record['catalog']), flush=True)
                return
            record['phase'] = 'awaiting_user_auth'
            save()
            # The CLI owns terminal input. No PIPE, tee, transcript or token args.
            login = subprocess.Popen(CLI + ['exec', '-it', NAME, '/usr/bin/timeout',
                '--signal=TERM', '--kill-after=10', '600',
                '/home/agent/.local/bin/devin-cli', 'auth', 'login', '--force-manual-token-flow'],
                start_new_session=True)
            try:
                code = login.wait(timeout=660)
            except BaseException:
                try:
                    os.killpg(login.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                login.wait(timeout=5)
                raise
            record['login_exit_code'] = code
            record['phase'] = 'login_command_ended'  # Not authentication acceptance.
        finally:
            for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
                signal.signal(sig, signal.SIG_IGN)
            errors = []
            try:
                if changed:
                    run('policy', 'deny', 'network', '--sandbox', NAME, '**')
                if not any(scoped_deny(r) and r['resources'] == ['**'] for r in rules()):
                    raise RuntimeError('Blanket deny restoration unverified')
                if any(allowed(h) is not False for h in HOSTS | {'example.com:443'}):
                    raise RuntimeError('Network deny restoration unverified')
                record['network_denied_after'] = True
                for rule_id in temporary_ids:
                    run('policy', 'rm', 'network', '--sandbox', NAME, '--id', rule_id)
            except BaseException as error:
                errors.append(type(error).__name__ + ':network_cleanup')
            try:
                run('stop', NAME)
                stopped()
                record['all_vms_stopped'] = True
            except BaseException as error:
                errors.append(type(error).__name__ + ':vm_cleanup')
            record.update(cleanup_errors=errors, phase='closed' if not errors else 'inspection_required')
            save()
            print('Cleanup complete.' if not errors else 'Cleanup needs inspection. Notify the assistant.', flush=True)
            if errors:
                raise RuntimeError('Authentication cleanup incomplete')


if __name__ == '__main__':
    import sys
    if len(sys.argv) == 3 and sys.argv[1] == '--login-role':
        select_login_target(sys.argv[2])
        main()
    elif (sys.argv[1:] == ['--recover-machine-deny'] or
          (len(sys.argv) == 3 and sys.argv[1] == '--recover-role')):
        if len(sys.argv) == 3:
            select_login_target(sys.argv[2])
        require_managed_namespace()
        with open('/tmp/e-base-devin-fleet-global.lock', 'r') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = recover_machine_denial()
            work = Path(tempfile.mkdtemp(prefix='network-recovery-', dir='/home/fleet/controller-validation'))
            atomic_write_json(work/'receipt.json', result)
            print('evidence=' + str(work), flush=True)
            print(json.dumps(result), flush=True)
    elif sys.argv[1:] == ['--inspect-policy']:
        require_managed_namespace()
        with open('/tmp/e-base-devin-fleet-global.lock', 'r') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            stopped()
            print(json.dumps(rules()), flush=True)
    elif not sys.argv[1:]:
        main()
    elif sys.argv[1:] == ['--check-policy']:
        main(check_policy=True)
    elif sys.argv[1:] == ['--catalog-check']:
        main(catalog_check=True)
    elif sys.argv[1:] == ['--shell-probe-evidence']:
        main(shell_probe_evidence=True)
    elif sys.argv[1:] == ['--shell-denial-probe']:
        main(shell_denial_probe=True)
    elif sys.argv[1:] == ['--eword-edit']:
        main(eword_edit=True)
    elif sys.argv[1:] == ['--eword-evidence']:
        main(eword_evidence=True)
    elif sys.argv[1:] == ['--file-probe-evidence']:
        main(file_probe_evidence=True)
    elif sys.argv[1:] == ['--file-tool-probe']:
        main(file_tool_probe=True)
    elif len(sys.argv[1:])==2 and sys.argv[1]=='--model-smoke-role':
        select_login_target(sys.argv[2])
        main(model_smoke=True)
    elif sys.argv[1:] == ['--model-smoke']:
        main(model_smoke=True)
    elif sys.argv[1:] == ['--smoke-evidence']:
        main(smoke_evidence=True)
    else:
        raise RuntimeError('Unknown action')
