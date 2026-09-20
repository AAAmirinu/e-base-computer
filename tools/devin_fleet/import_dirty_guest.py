"""One-shot trusted migration helper, executed inside the destination VM only.

Reads an explicit host inventory argument; never discovers or executes project
code. Requires a new destination. Failure leaves evidence for manual recovery.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tarfile


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    request = json.loads(sys.argv[1])
    role = request['role']
    if role not in ('applications', 'stdlib', 'devtools'):
        raise ValueError('Unsupported role')
    base = Path('/home/agent/workspace')
    incoming = base / ('migration-' + role + '-20260917')
    target = base / role
    for path in (Path('/home'), Path('/home/agent'), base, incoming):
        if not stat.S_ISDIR(path.lstat().st_mode):
            raise ValueError('Untrusted workspace parent')
    if os.path.lexists(target):
        raise ValueError('Destination already exists; no automatic overwrite')
    bundle = incoming / (role + '.bundle')
    overlay = incoming / 'overlay.tar'
    for path, key in ((bundle, 'bundle_sha256'), (overlay, 'overlay_sha256')):
        if digest(path.read_bytes()) != request[key]:
            raise ValueError('Artifact digest mismatch')
    expected = request['files']
    payload = {}
    with tarfile.open(overlay, 'r:') as archive:
        for member in archive.getmembers():
            name = member.name
            if (name not in expected or name in payload or not member.isfile()
                    or member.size > 4 * 1024 * 1024
                    or not re.fullmatch(r'[A-Za-z0-9_./-]+', name)
                    or name.startswith('/')
                    or any(p in ('', '.', '..', '.git', '.fleet', '.devin') for p in name.split('/'))):
                raise ValueError('Unexpected overlay member')
            data = archive.extractfile(member).read()
            if len(data) != expected[name]['size'] or digest(data) != expected[name]['sha256']:
                raise ValueError('Overlay member mismatch')
            payload[name] = data
    if set(payload) != set(expected):
        raise ValueError('Missing overlay files')
    env = {'PATH': '/usr/bin:/bin', 'HOME': '/nonexistent', 'LC_ALL': 'C',
           'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null'}

    def git(*args):
        return subprocess.check_output(['git', '-c', 'core.hooksPath=/dev/null',
                                       '-c', 'core.fsmonitor=false', '-c', 'core.excludesFile=',
                                       *args], env=env)

    git('clone', '--template=', '--no-checkout', str(bundle), str(target))
    git('-C', str(target), 'checkout', '--detach', request['head'])
    if git('-C', str(target), 'rev-parse', 'HEAD^{tree}').decode().strip() != request['tree']:
        raise ValueError('Tree mismatch')
    if git('-C', str(target), 'status', '--porcelain=v1', '-z', '--untracked-files=all'):
        raise ValueError('Initial checkout not clean')
    for name, data in payload.items():
        dest = target / name
        current = target
        for component in name.split('/')[:-1]:
            current = current / component
            if not current.exists():
                current.mkdir()
            if not stat.S_ISDIR(current.lstat().st_mode):
                raise ValueError('Non-directory overlay parent')
        if os.path.lexists(dest) and not stat.S_ISREG(dest.lstat().st_mode):
            raise ValueError('Non-regular overlay target')
        # No agent runs concurrently in this one-shot, stopped-fleet migration.
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o644)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if digest(dest.read_bytes()) != expected[name]['sha256']:
            raise ValueError('Destination digest mismatch')
    actual = git('-C', str(target), 'status', '--porcelain=v1', '-z', '--untracked-files=all')
    entries = sorted(x.decode('utf-8') for x in actual.split(b'\0') if x)
    if entries != sorted(request['status']):
        raise ValueError('Index/worktree status mismatch: ' + repr(entries))
    git('-C', str(target), 'diff', '--cached', '--exit-code')
    git('-C', str(target), 'fsck', '--full')
    print('DIRTY_IMPORT_VERIFIED ' + json.dumps(request, sort_keys=True))


if __name__ == '__main__':
    main()
