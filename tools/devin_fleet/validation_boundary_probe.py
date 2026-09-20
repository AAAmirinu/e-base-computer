"""Trusted Linux container probe; no credentials read and no source executed.

Run before project source is introduced, via a cleared environment. A successful
probe covers only these observations, not full VM isolation or lifecycle safety.
"""
import json
import os
from pathlib import Path


SENSITIVE_PATHS = ('/var/run/docker.sock', '/run/docker.sock', '/run/host-services',
                   '/home/agent', '/root/.ssh', '/mnt/c', '/mnt/f', '/host',
                   '/run/sandbox/source')

# Explicit Docker pseudo/masked mount targets, not a prefix allowance. A new
# runtime layout must be reviewed before admission, never silently accepted.
MOUNT_TARGETS = frozenset(('/', '/work', '/tmp', '/proc', '/dev', '/dev/pts', '/sys',
    '/sys/fs/cgroup', '/dev/mqueue', '/dev/shm', '/etc/resolv.conf', '/etc/hostname',
    '/etc/hosts', '/proc/bus', '/proc/fs', '/proc/irq', '/proc/sys', '/proc/sysrq-trigger',
    '/proc/acpi', '/proc/interrupts', '/proc/kcore', '/proc/keys', '/proc/latency_stats',
    '/proc/timer_list', '/proc/timer_stats', '/proc/sched_debug', '/proc/scsi',
    '/sys/firmware', '/sys/devices/virtual/powercap'))


def _read(path):
    with open(path, encoding='utf-8', errors='strict') as stream:
        value = stream.read(65537)
    if len(value) > 65536:
        raise ValueError('Probe input exceeds bound')
    return value


def collect():
    # Deliberately no environment values, socket contents or credential files.
    status = {}
    for line in _read('/proc/self/status').splitlines():
        key, _, value = line.partition(':')
        if key in ('CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb', 'NoNewPrivs', 'Seccomp'):
            status[key] = value.strip()
    mounts = []
    for line in _read('/proc/self/mountinfo').splitlines():
        before, sep, after = line.partition(' - ')
        fields, extra = before.split(), after.split()
        if not sep or len(fields) < 6 or len(extra) < 3:
            raise ValueError('Malformed mount record')
        mounts.append({'target': fields[4], 'options': fields[5].split(','), 'fs': extra[0]})
    return {'schema': 1, 'uid': os.getuid(), 'euid': os.geteuid(), 'gid': os.getgid(),
            'egid': os.getegid(), 'groups': os.getgroups(), 'status': status,
            'environment_keys': sorted(os.environ),
            'interfaces': sorted(p.name for p in Path('/sys/class/net').iterdir()),
            'ipv4_routes': _read('/proc/net/route').splitlines()[1:],
            'ipv6_routes': _read('/proc/net/ipv6_route').splitlines(),
            'unix_sockets': _read('/proc/net/unix').splitlines()[1:],
            'sensitive_paths': {p: os.path.lexists(p) for p in SENSITIVE_PATHS},
            'mounts': mounts}


def verify(observed):
    """Return limited evidence or reject. Never turns on project execution."""
    required = {'schema', 'uid', 'euid', 'gid', 'egid', 'groups', 'status', 'environment_keys',
                'interfaces', 'ipv4_routes', 'ipv6_routes', 'unix_sockets', 'sensitive_paths', 'mounts'}
    if not isinstance(observed, dict) or set(observed) != required or type(observed['schema']) is not int or observed['schema'] != 1:
        raise ValueError('Invalid boundary observation schema')
    for key in ('uid', 'euid', 'gid', 'egid'):
        if type(observed[key]) is not int or observed[key] != 65532:
            raise ValueError('Unexpected validation identity')
    if observed['groups'] not in ([], [65532]):
        raise ValueError('Supplementary groups present')
    status = observed['status']
    if not isinstance(status, dict):
        raise ValueError('Missing process security status')
    for key in ('CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb'):
        value = status.get(key)
        if not isinstance(value, str) or value != '0000000000000000':
            raise ValueError('Capability set not empty')
    if status.get('NoNewPrivs') != '1' or status.get('Seccomp') != '2':
        raise ValueError('Privilege/seccomp boundary missing')
    if observed['environment_keys'] != ['HOME', 'LANG', 'PATH']:
        raise ValueError('Unexpected environment keys')
    if observed['interfaces'] != ['lo'] or observed['ipv4_routes'] != []:
        raise ValueError('External network interface/route present')
    if not isinstance(observed['ipv6_routes'], list):
        raise ValueError('Missing IPv6 observations')
    for route in observed['ipv6_routes']:
        if not isinstance(route, str) or len(route.split()) != 10 or route.split()[-1] != 'lo':
            raise ValueError('Unexpected IPv6 route')
    if observed['unix_sockets'] != []:
        raise ValueError('Unexpected Unix socket present')
    paths = observed['sensitive_paths']
    if not isinstance(paths, dict) or set(paths) != set(SENSITIVE_PATHS) or any(value is not False for value in paths.values()):
        raise ValueError('Sensitive path visible or observation incomplete')
    mounts = observed['mounts']
    if not isinstance(mounts, list) or len(mounts) > 256:
        raise ValueError('Invalid mount observations')
    indexed = {}
    for mount in mounts:
        if not isinstance(mount, dict) or set(mount) != {'target', 'options', 'fs'}:
            raise ValueError('Invalid mount record')
        target, options, fs = mount['target'], mount['options'], mount['fs']
        if (not isinstance(target, str) or target in indexed or not isinstance(options, list) or
                not all(isinstance(option, str) for option in options) or not isinstance(fs, str)):
            raise ValueError('Malformed or stacked mount')
        if fs in ('9p', 'virtiofs', 'cifs', 'drvfs', 'fuse', 'fuse.sshfs', 'nfs', 'nfs4'):
            raise ValueError('Shared filesystem visible')
        if target not in MOUNT_TARGETS:
            raise ValueError('Unexpected mount target')
        indexed[target] = mount
    root = indexed.get('/')
    if root is None or 'ro' not in root['options'] or 'rw' in root['options']:
        raise ValueError('Root filesystem is writable')
    for target in ('/work', '/tmp'):
        mount = indexed.get(target)
        if mount is None or mount['fs'] != 'tmpfs' or not {'rw', 'nosuid', 'nodev'} <= set(mount['options']):
            raise ValueError('Private scratch mount missing')
    if 'noexec' not in indexed['/tmp']['options']:
        raise ValueError('Temporary directory permits execution')
    return {'schema': 1, 'observations_verified': True, 'source_executed': False,
            'full_isolation_accepted': False}


if __name__ == '__main__':
    observation = collect()
    result = verify(observation)
    print(json.dumps({'observation': observation, 'result': result}, sort_keys=True))
