"""Explicit maintenance cutover, never a model launcher or automatic recovery.

Run only after migrating all callers to the managed namespace entry. On failure
leave ordinary daemon restoration to inspection; never silently weaken isolation.
"""
import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import tempfile
import time

UNIT = 'e-base-sandboxd.service'
ENTRY = Path('/usr/local/libexec/e-base-managed-status.py')
UNIT_PATH = Path('/etc/systemd/system') / UNIT
ROOT = Path('/home/fleet/controller-validation')
PIDFILE = Path('/home/fleet/.local/state/sandboxes/sandboxes/sandboxd/sandboxd.pid')
HASHES = {
    Path('/usr/local/libexec/e-base-managed-cli-guard.py'): '32f1e2a00df4c686ba3b4c27a2ca92035e3bb9ba74af27bff79bbe49d6d6a788',
    ENTRY: 'bc85d5b41c81538fd85a1870881f375f8dd3213d9525453a0e7be953b0e0ba48',
    UNIT_PATH: '1a16c24ba8a7c95cb51433ba6c46855aa605dd01812cf73b2ddb12b8875111cc',
    Path('/etc/tmpfiles.d/e-base-fleet.conf'): 'a5cf539d7d61c95657e62ca92b8b8dcd098d789eb8c47a00a4160f57e700aeff',
}
CALLER_HASHES = {
    Path('/home/fleet/sbx-headless.sh'): '41687cd8f15d7372ef086b49e7cc2bf161eaabea8ed52cb22982534824a8fac4',
    ROOT/'sandbox_control.py': '552d36732ccd6bdbbc869828d37cc6970c54de3b475b79d254406f29bbdd97c6',
    ROOT/'managed_cli_guard.py': '32f1e2a00df4c686ba3b4c27a2ca92035e3bb9ba74af27bff79bbe49d6d6a788',
}
# This narrowly scoped migration path must stop the *verified ordinary* daemon.
# Normal clients use the guarded entry and cannot operate outside managed namespaces.
CLI = ['/usr/sbin/runuser', '-u', 'fleet', '--', '/usr/bin/sbx']
ROLES = {'machine', 'coordinator', 'toolchain', 'kernel', 'stdlib', 'storage',
         'services', 'applications', 'devtools', 'assurance'}


def identities(value):
    rows = value['sandboxes']
    names = [row['name'] for row in rows]
    ids = [row['id'] for row in rows]
    if (len(rows) != 11 or len(set(names)) != 11 or len(set(ids)) != 11 or
            any(row['status'] != 'stopped' for row in rows)):
        raise RuntimeError('Exactly eleven distinct stopped sandboxes required')
    return dict(zip(names, ids))


def expected_identities(registry):
    if (registry.get('production_enabled') is not False or
            registry.get('distro') != 'EBase-Sandboxes' or registry.get('user') != 'fleet' or
            set(registry['roles']) != ROLES):
        raise RuntimeError('Stopped maintenance registry required')
    result = {v['name']: v['id'] for v in registry['roles'].values()}
    result['e-base-validation'] = '84a0fc99-4cbb-4383-a1df-4c22bbe0d2e6'
    if len(result) != 11 or len(set(result.values())) != 11:
        raise RuntimeError('Registry identities must be distinct')
    return result


def command(args):
    child = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, start_new_session=True)
    try:
        output, _ = child.communicate(timeout=40)
    except BaseException:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.communicate(timeout=5)
        raise
    if child.returncode:
        raise RuntimeError('Maintenance command failed, exit=' + str(child.returncode))
    return output


def verify_installed():
    verified = {}
    for path, digest in HASHES.items():
        for parent in path.parents:
            info = parent.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
                raise RuntimeError('Untrusted installed parent')
        info = path.lstat()
        content = path.read_bytes() if stat.S_ISREG(info.st_mode) else b''
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or
                stat.S_IMODE(info.st_mode) != 0o644 or
                hashlib.sha256(content).hexdigest() != digest):
            raise RuntimeError('Installed artifact identity mismatch')
        verified[path] = content
    return verified


def verify_callers():
    """Do not cut over while deployed trusted clients still lack the guard."""
    for path, digest in CALLER_HASHES.items():
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid not in (0, 1000) or
                info.st_mode & 0o022 or hashlib.sha256(path.read_bytes()).hexdigest() != digest):
            raise RuntimeError('Deployed maintenance callers have not been migrated')


def validate_loaded_service(values):
    if (values.get('ActiveState') != 'inactive' or values.get('MainPID') != '0' or
            values.get('FragmentPath') != str(UNIT_PATH) or values.get('DropInPaths') != '' or
            values.get('NeedDaemonReload') != 'no' or values.get('UnitFileState') != 'static'):
        raise RuntimeError('Loaded service does not match inactive installed definition')


def loaded_service():
    output = command(['/usr/bin/systemctl', 'show', UNIT,
        '-p', 'ActiveState,MainPID,FragmentPath,DropInPaths,NeedDaemonReload,UnitFileState'])
    return dict(line.split('=', 1) for line in output.splitlines() if '=' in line)


def process_start(pid):
    return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]


def wait_pidfile(pid):
    """Wait for initialization metadata only; never use a probing sbx client."""
    proc = Path(f'/proc/{pid}')
    start = process_start(pid)
    deadline = time.monotonic() + 10
    while True:
        if process_start(pid) != start:
            raise RuntimeError('Managed daemon generation changed during readiness')
        status = (proc/'status').read_text()
        namespace_pids = [line.split()[1:] for line in status.splitlines() if line.startswith('NSpid:')]
        try:
            value = PIDFILE.read_text().strip()
        except FileNotFoundError:
            value = ''
        if (len(namespace_pids) == 1 and len(namespace_pids[0]) >= 2 and
                value == namespace_pids[0][-1] and value.isdecimal() and int(value) >= 1):
            if (os.readlink(proc/'exe') != '/usr/bin/sbx' or
                    (proc/'cmdline').read_bytes() != b'/usr/bin/sbx\0daemon\0start\0' or
                    status.split('Uid:', 1)[1].splitlines()[0].split() != ['1000']*4):
                raise RuntimeError('Unexpected managed daemon readiness identity')
            return
        if time.monotonic() >= deadline:
            raise RuntimeError('Managed daemon PID file readiness timed out')
        time.sleep(0.1)


def validate_original(pid, start):
    proc = Path(f'/proc/{pid}')
    if (pid <= 1 or process_start(pid) != start or
            os.readlink(proc/'exe') != '/usr/bin/sbx' or
            (proc/'cmdline').read_bytes() != b'/usr/bin/sbx\0daemon\0start\0' or
            (proc/'status').read_text().split('Uid:', 1)[1].splitlines()[0].split() != ['1000']*4 or
            os.stat(proc/'ns/pid').st_ino != os.stat('/proc/self/ns/pid').st_ino):
        raise RuntimeError('Original daemon identity mismatch')


def save_receipt(path, record):
    temporary = path.with_suffix('.tmp')
    with temporary.open('x', encoding='utf-8') as output:
        json.dump(record, output, sort_keys=True)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def cutover(expected, old_pid, old_start, managed, save):
    record = {'schema': 1, 'phase': 'prepared', 'models_executed': False,
              'ordinary_restore_attempted': False, 'identities': expected}
    save(record)
    start_attempted = False
    try:
        validate_original(old_pid, old_start)
        validate_loaded_service(loaded_service())
        record['phase'] = 'stopping_original'
        save(record)
        command(CLI + ['daemon', 'stop'])
        # Do not start another manager while the previous process still exists.
        if Path(f'/proc/{old_pid}').exists():
            raise RuntimeError('Original daemon has not exited; inspection required')
        record['phase'] = 'starting_managed'
        save(record)
        start_attempted = True
        command(['/usr/bin/systemctl', 'start', UNIT])
        # No client until systemd exposes the required effective restrictions.
        pid = managed.validate_service(managed.service_info(UNIT))
        wait_pidfile(pid)
        if identities(managed.run_status()) != expected:
            raise RuntimeError('Managed inventory identity mismatch')
        record['controller_status'] = managed.run_status(controller=True)
        record.update(phase='maintenance_managed', all_vms_stopped=True)
        save(record)
    except BaseException as error:
        record.update(phase='inspection_required', error_type=type(error).__name__)
        if start_attempted:
            try:
                command(['/usr/bin/systemctl', 'stop', UNIT])
                record['managed_stop_verified'] = (
                    command(['/usr/bin/systemctl', 'show', UNIT, '-p', 'MainPID', '--value']).strip() == '0')
            except BaseException:
                record['managed_stop_verified'] = False
        try:
            save(record)
        except BaseException as journal_error:
            error.add_note('Failure receipt could not be persisted: ' + type(journal_error).__name__)
        raise
    return record


def main():
    import fcntl
    import types
    import sys
    if sys.argv[1:] != ['--maintenance-cutover']:
        raise RuntimeError('Explicit --maintenance-cutover required; no resume action')
    if os.getuid() != 0 or os.environ.get('WSL_DISTRO_NAME') != 'EBase-Sandboxes':
        raise RuntimeError('Dedicated distro root required')
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda number, frame: (_ for _ in ()).throw(RuntimeError('Interrupted')))
    with open('/tmp/e-base-devin-fleet-global.lock', 'r') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        verified = verify_installed()
        verify_callers()
        validate_loaded_service(loaded_service())
        old_pid = int(PIDFILE.read_text().strip())
        if old_pid <= 1:
            raise RuntimeError('Invalid ordinary daemon PID')
        old_start = process_start(old_pid)
        validate_original(old_pid, old_start)
        expected = expected_identities(json.loads((ROOT/'sandbox-registry.json').read_text()))
        if identities(json.loads(command(CLI + ['ls', '--json']))) != expected:
            raise RuntimeError('Initial inventory mismatch')
        managed = types.ModuleType('installed_managed_status')
        exec(compile(verified[ENTRY], str(ENTRY), 'exec'), managed.__dict__)
        work = Path(tempfile.mkdtemp(prefix='managed-cutover-', dir=ROOT))
        print('evidence=' + str(work), flush=True)
        record = cutover(expected, old_pid, old_start, managed,
                         lambda value: save_receipt(work/'receipt.json', value))
        print(json.dumps(record), flush=True)


if __name__ == '__main__':
    main()
