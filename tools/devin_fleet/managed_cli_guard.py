"""Refuse legacy sbx clients outside the permanent managed daemon namespaces.

This is a controller misuse guard, not a hostile-user security boundary. It
never starts a daemon or retries elsewhere. A daemon dying after this check can
still trigger sbx fallback, but only inside the checked namespaces.
"""
import os
from pathlib import Path
import sys
import subprocess

PIDFILE = Path('/home/fleet/.local/state/sandboxes/sandboxes/sandboxd/sandboxd.pid')
CGROUP = '/system.slice/e-base-sandboxd.service'


def validate_service(values):
    required = {'ActiveState': 'active', 'SubState': 'running', 'User': 'fleet',
                'PrivatePIDs': 'yes', 'Restart': 'no', 'KillMode': 'control-group'}
    if any(values.get(key) != value for key, value in required.items()):
        raise RuntimeError('Permanent service isolation is inactive or weakened')
    if not {'/mnt/wslg', '/tmp/.X11-unix', '/run/WSL', '/run/user'} <= set(
            values.get('InaccessiblePaths', '').split()):
        raise RuntimeError('Required display restrictions missing')


def service_info():
    output = subprocess.run(['/usr/bin/systemctl', 'show', 'e-base-sandboxd.service',
        '-p', 'ActiveState,SubState,User,PrivatePIDs,Restart,KillMode,InaccessiblePaths,MainPID'],
        check=True, capture_output=True, text=True, timeout=10,
        env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C.UTF-8'}).stdout
    return dict(line.split('=', 1) for line in output.splitlines() if '=' in line)


def validate_metadata(pid_text, executable, argv, status, cgroup, own_ns, daemon_ns):
    if (not pid_text.isascii() or not pid_text.isdecimal() or int(pid_text) < 1 or
            executable != '/usr/bin/sbx' or argv != b'/usr/bin/sbx\0daemon\0start\0'):
        raise RuntimeError('Managed daemon identity missing or incorrect')
    uid_lines = [line.split()[1:] for line in status.splitlines() if line.startswith('Uid:')]
    if uid_lines != [['1000'] * 4]:
        raise RuntimeError('Managed daemon UID mismatch')
    # Unified cgroup v2 is required. An outer sbx daemon or another service is
    # not an acceptable fallback. Do not accept a suffix/substring match.
    if cgroup.splitlines() != ['0::' + CGROUP]:
        raise RuntimeError('Daemon is not owned by the permanent managed service')
    if set(own_ns) != {'mnt', 'pid'} or own_ns != daemon_ns:
        raise RuntimeError('Use the managed namespace entry; outer clients forbidden')


def require_managed_namespace():
    if (sys.platform != 'linux' or os.getuid() != 1000 or
            os.environ.get('WSL_DISTRO_NAME') != 'EBase-Sandboxes'):
        raise RuntimeError('Dedicated fleet Linux context required')
    before = service_info()
    validate_service(before)
    pid_text = PIDFILE.read_text().strip()
    if not pid_text.isascii() or not pid_text.isdecimal() or int(pid_text) < 1:
        raise RuntimeError('Invalid namespace-local daemon PID')
    proc = Path('/proc') / pid_text
    start = (proc/'stat').read_text().rsplit(')', 1)[1].split()[19]
    own_ns = {kind: os.stat('/proc/self/ns/' + kind).st_ino for kind in ('mnt', 'pid')}
    daemon_ns = {kind: os.stat(proc/'ns'/kind).st_ino for kind in ('mnt', 'pid')}
    validate_metadata(pid_text, os.readlink(proc/'exe'), (proc/'cmdline').read_bytes(),
                      (proc/'status').read_text(), (proc/'cgroup').read_text(), own_ns, daemon_ns)
    if ((proc/'stat').read_text().rsplit(')', 1)[1].split()[19] != start or
            PIDFILE.read_text().strip() != pid_text or service_info() != before):
        raise RuntimeError('Daemon changed during managed namespace check')


if __name__ == '__main__':
    if sys.argv[1:]:
        raise RuntimeError('No guard overrides accepted')
    require_managed_namespace()
