"""Guest-only, bounded metadata inventory; NOT an isolation attestation.

No network calls, child processes, credential reads, or project imports.
Only fixed path presence and selected proc metadata leave the guest.
"""
import json
import os
import stat
import time
from pathlib import Path

PATHS = ('/mnt/c', '/mnt/f', '/host', '/host_mnt', '/run/sandbox/source',
         '/mnt/wslg', '/run/WSL', '/tmp/.X11-unix',
         '/home/agent/.agents/skills', '/home/agent/.devin/skills',
         '/var/run/docker.sock', '/run/user/1000/bus')
VARIABLES = ('DISPLAY', 'WAYLAND_DISPLAY', 'WSL_INTEROP', 'SSH_AUTH_SOCK',
             'DBUS_SESSION_BUS_ADDRESS', 'DEVIN_API_KEY', 'OPENAI_API_KEY',
             'ANTHROPIC_API_KEY', 'GH_TOKEN', 'GITHUB_TOKEN')
SHARED_FS = ('9p', 'virtiofs', 'cifs', 'drvfs', 'smb3', 'vboxsf', 'fuse.sshfs')
MOUNT_TARGETS = ('/', '/etc/hosts', '/etc/hostname', '/etc/resolv.conf',
                 '/run', '/run/sandbox', '/run/host-services', '/var/lib/docker',
                 '/var/run/docker.sock', '/mnt', '/home/agent', '/workspace')


def classify_mounts(mountinfo):
    result = []
    for line in mountinfo.splitlines():
        before, separator, after = line.partition(' - ')
        fields, tail = before.split(), after.split()
        if not separator or len(fields) < 6 or len(tail) < 3:
            raise ValueError('Malformed mount inventory')
        if tail[0] in SHARED_FS:
            result.append(dict(filesystem=tail[0],
                target=fields[4] if fields[4] in MOUNT_TARGETS else 'unclassified',
                mount_readonly='ro' in fields[5].split(','),
                filesystem_readonly='ro' in tail[2].split(',')))
    return result


def path_metadata(path):
    # lstat does not follow the final symlink; never connect to sockets.
    try:
        info = os.lstat(path)
    except OSError as error:
        return dict(present=False, errno=error.errno)
    kind = ('socket' if stat.S_ISSOCK(info.st_mode) else 'symlink' if stat.S_ISLNK(info.st_mode)
            else 'directory' if stat.S_ISDIR(info.st_mode) else 'other')
    return dict(present=True, kind=kind, uid=info.st_uid, gid=info.st_gid,
                mode=stat.S_IMODE(info.st_mode))


def bounded_read(path, limit=1048576):
    with Path(path).open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('Metadata size limit exceeded')
    return raw.decode('utf-8', errors='strict')


def docker_inodes(unix_sockets):
    """Select only fixed Docker endpoints, never disclose other socket paths."""
    found = set()
    for line in unix_sockets.splitlines()[1:]:
        fields = line.split(maxsplit=7)
        if len(fields) == 8 and fields[7] in ('/run/docker.sock', '/var/run/docker.sock'):
            if not fields[6].isascii() or not fields[6].isdigit():
                raise ValueError('Invalid socket inode')
            found.add(fields[6])
    return found


def docker_owners(unix_sockets):
    inodes = docker_inodes(unix_sockets)
    result = dict(endpoint_inodes=len(inodes), dockerd_owners=0, other_owners=0,
                  inaccessible_processes=0, scan_complete=True,
                  host_boundary_proven=False)
    if not inodes:
        return result
    targets = {'socket:['+inode+']' for inode in inodes}
    deadline = time.monotonic()+2
    processes = 0
    with os.scandir('/proc') as entries:
        for entry in entries:
            if not entry.name.isascii() or not entry.name.isdigit():
                continue
            processes += 1
            if processes > 1024 or time.monotonic() >= deadline:
                result['scan_complete'] = False
                break
            try:
                matched = False
                with os.scandir(entry.path+'/fd') as descriptors:
                    for index, descriptor in enumerate(descriptors):
                        if index >= 2048 or time.monotonic() >= deadline:
                            result['scan_complete'] = False
                            break
                        if os.readlink(descriptor.path) in targets:
                            matched = True
                            break
                if matched:
                    # No cmdline, environ, executable, or fd content is read.
                    kind = 'dockerd_owners' if bounded_read(entry.path+'/comm', 64).strip() == 'dockerd' else 'other_owners'
                    result[kind] += 1
            except OSError:
                result['inaccessible_processes'] += 1
                result['scan_complete'] = False
    return result


def summarize(mountinfo, unix_sockets, meminfo, *, uid, cpu_count, paths, variables):
    """Pure parser. Never return arbitrary mount paths, socket names or env values."""
    if type(uid) is not int or uid < 0 or type(cpu_count) is not int or cpu_count < 1:
        raise ValueError('Invalid guest identity or CPU observation')
    if (set(paths) != set(PATHS) or set(variables) != set(VARIABLES)
            or any(type(x) is not bool for x in [*paths.values(), *variables.values()])):
        raise ValueError('Fixed presence observations required')
    shared = {name: 0 for name in SHARED_FS}
    mounts = mountinfo.splitlines()
    if not mounts:
        raise ValueError('Mount inventory missing')
    for line in mounts:
        before, separator, after = line.partition(' - ')
        fields = after.split()
        if not separator or len(before.split()) < 6 or len(fields) < 3:
            raise ValueError('Malformed mount inventory')
        if fields[0] in shared:
            shared[fields[0]] += 1
    sockets = unix_sockets.splitlines()
    if not sockets or sockets[0].split() != ['Num', 'RefCount', 'Protocol', 'Flags', 'Type', 'St', 'Inode', 'Path']:
        raise ValueError('Socket inventory missing')
    abstract_display = 0
    for line in sockets[1:]:
        fields = line.split(maxsplit=7)
        if len(fields) < 7:
            raise ValueError('Malformed socket inventory')
        if len(fields) == 8 and fields[7].startswith(('@/tmp/.X11-unix/', '@wayland-')):
            abstract_display += 1
    totals = [line.split() for line in meminfo.splitlines() if line.startswith('MemTotal:')]
    if (len(totals) != 1 or len(totals[0]) != 3 or totals[0][2] != 'kB'
            or not totals[0][1].isascii() or not totals[0][1].isdigit() or int(totals[0][1]) <= 0):
        raise ValueError('Memory observation missing')
    return dict(schema=1, uid=uid, logical_cpu_count=cpu_count,
                mem_total_kib=int(totals[0][1]), mount_count=len(mounts),
                shared_filesystem_counts=shared, abstract_display_socket_count=abstract_display,
                fixed_paths_present=dict(paths), variable_names_present=dict(variables),
                network_attempted=False, credentials_read=False, model_executed=False,
                full_boundary_accepted=False)


def collect():
    mounts = bounded_read('/proc/self/mountinfo')
    sockets = bounded_read('/proc/net/unix')
    result = summarize(mounts, sockets,
                     bounded_read('/proc/meminfo', 65536), uid=os.getuid(),
                     cpu_count=os.cpu_count(), paths={p: os.path.lexists(p) for p in PATHS},
                     variables={key: key in os.environ for key in VARIABLES})
    result['shared_mount_details'] = classify_mounts(mounts)
    result['docker_socket_metadata'] = path_metadata('/var/run/docker.sock')
    result['docker_socket_owners'] = docker_owners(sockets)
    # Names/values of environment-selected paths never leave this process.
    ssh = os.environ.get('SSH_AUTH_SOCK')
    if ssh and ssh.startswith(('/run/', '/tmp/')) and '..' not in ssh.split('/'):
        result['ssh_socket_metadata'] = path_metadata(ssh)
    else:
        result['ssh_socket_metadata'] = {'path_not_in_probe_scope': True}
    return result


if __name__ == '__main__':
    print(json.dumps(collect(), sort_keys=True), flush=True)
