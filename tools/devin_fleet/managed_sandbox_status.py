"""Root-only status entry into an existing confined manager; never autostart it.

No arbitrary command or caller-selected unit is accepted by the CLI. Namespace
handles are pinned before dropping to fleet; fallback, if any inside sbx, cannot
escape those namespaces. This is maintenance status, not model admission.
"""
import json
import os
from pathlib import Path
import subprocess
import signal

UNIT = 'e-base-sandboxd.service'
TEST_UNIT = 'e-base-sandboxd-boundary-test.service'
CONTROL_ROOT = '/home/fleet/controller-validation'
ROLES = frozenset(('machine', 'coordinator', 'toolchain', 'kernel', 'stdlib',
                   'storage', 'services', 'applications', 'devtools', 'assurance'))


def parse_status(output, controller):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('Duplicate status field')
            value[key] = item
        return value
    value = json.loads(output, object_pairs_hook=unique)
    if controller and (not isinstance(value, dict) or
            set(value) != {'roles', 'stop_requested', 'mode', 'resume_available'} or
            value.get('mode') != 'maintenance_only' or value.get('resume_available') is not False or
            type(value.get('stop_requested')) is not bool or not isinstance(value.get('roles'), dict) or
            set(value['roles']) != ROLES or any(s != 'stopped' for s in value['roles'].values())):
        raise RuntimeError('Controller is not a stopped maintenance-only inventory')
    return value


def status_command(controller=False):
    if type(controller) is not bool:
        raise ValueError('Explicit status action required')
    if controller:
        return ['/usr/bin/python3', '-E', '-s', CONTROL_ROOT+'/sandbox_driver.py',
                '--registry', CONTROL_ROOT+'/sandbox-registry.json',
                '--root', CONTROL_ROOT+'/managed-maintenance', 'status']
    return ['/bin/sh', '/home/fleet/sbx-headless.sh', 'ls', '--json']


def validate_service(values):
    if (values.get('ActiveState') != 'active' or values.get('SubState') != 'running' or
            values.get('User') != 'fleet' or values.get('PrivatePIDs') != 'yes'):
        raise RuntimeError('Managed service is not active with required isolation')
    if values.get('Restart') != 'no' or values.get('KillMode') != 'control-group':
        raise RuntimeError('Unexpected service restart/cleanup policy')
    paths = values.get('InaccessiblePaths', '').split()
    if not {'/mnt/wslg', '/tmp/.X11-unix', '/run/WSL', '/run/user'} <= set(paths):
        raise RuntimeError('Required display path restrictions missing')
    pid = values.get('MainPID', '')
    if not pid.isascii() or not pid.isdecimal() or int(pid) <= 1:
        raise RuntimeError('Invalid managed daemon PID')
    return int(pid)


def service_info(unit):
    if unit not in (UNIT, TEST_UNIT):
        raise ValueError('Unknown managed service')
    output = subprocess.run(['/usr/bin/systemctl', 'show', unit,
        '--property=ActiveState,SubState,User,PrivatePIDs,InaccessiblePaths,MainPID,Restart,KillMode'],
        check=True, capture_output=True, text=True, timeout=10).stdout
    return dict(line.split('=', 1) for line in output.splitlines() if '=' in line)


def run_status(*, unit=UNIT, controller=False):
    """Caller must hold fleet lock; test unit is internal maintenance support."""
    if os.getuid() != 0 or os.environ.get('WSL_DISTRO_NAME') != 'EBase-Sandboxes':
        raise RuntimeError('Dedicated distro root required')
    fixed_command = status_command(controller)
    pid = validate_service(service_info(unit))
    proc = Path('/proc')/str(pid)
    start = (proc/'stat').read_text().rsplit(')', 1)[1].split()[19]
    if (os.readlink(proc/'exe') != '/usr/bin/sbx' or
            (proc/'cmdline').read_bytes() != b'/usr/bin/sbx\0daemon\0start\0' or
            (proc/'status').read_text().split('Uid:', 1)[1].splitlines()[0].split() != ['1000']*4):
        raise RuntimeError('Unexpected manager process identity')
    descriptors = []
    try:
        for kind in ('mnt', 'pid'):
            descriptor = os.open(proc/'ns'/kind, os.O_RDONLY)
            descriptors.append(descriptor)
            if os.fstat(descriptor).st_ino == os.stat('/proc/self/ns/'+kind).st_ino:
                raise RuntimeError('Manager is not in a separate namespace')
        if (validate_service(service_info(unit)) != pid or
                (proc/'stat').read_text().rsplit(')', 1)[1].split()[19] != start):
            raise RuntimeError('Manager changed while pinning namespaces')
        args = ['/usr/bin/nsenter', '--mount=/proc/self/fd/'+str(descriptors[0]),
                '--pid=/proc/self/fd/'+str(descriptors[1]), '--',
                '/usr/sbin/runuser', '-u', 'fleet', '--'] + fixed_command
        child = subprocess.Popen(args, pass_fds=descriptors, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, start_new_session=True, env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin',
            'HOME': '/home/fleet', 'WSL_DISTRO_NAME': 'EBase-Sandboxes', 'LANG': 'C.UTF-8'})
        try:
            output, _ = child.communicate(timeout=45 if controller else 30)
        except BaseException:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.communicate(timeout=5)
            raise
        if child.returncode:
            raise RuntimeError('Managed status client failed')
        if (validate_service(service_info(unit)) != pid or
                (proc/'stat').read_text().rsplit(')', 1)[1].split()[19] != start):
            raise RuntimeError('Manager changed during status request')
        return parse_status(output, controller)
    finally:
        for descriptor in descriptors:
            os.close(descriptor)


def main():
    import fcntl
    import sys
    if sys.argv[1:] not in ([], ['--controller-status']):
        raise ValueError('Only fixed status actions accepted')
    with open('/tmp/e-base-devin-fleet-global.lock', 'r') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        print(json.dumps(run_status(controller=bool(sys.argv[1:]))), flush=True)


if __name__ == '__main__':
    main()
