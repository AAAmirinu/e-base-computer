"""Root-only targeted lock bootstrap verification; no daemon/VM or cleanup call."""
import json
import os
from pathlib import Path
import stat
import subprocess

LOCK = Path('/tmp/e-base-devin-fleet-global.lock')
CONFIG = '/etc/tmpfiles.d/e-base-fleet.conf'


def identity():
    value = LOCK.lstat()
    if (not stat.S_ISREG(value.st_mode) or value.st_uid != 1000 or value.st_gid != 1000 or
            stat.S_IMODE(value.st_mode) != 0o600 or value.st_nlink != 1):
        raise RuntimeError('Unexpected lock object; refusing repair/replacement')
    return value.st_dev, value.st_ino


def create():
    subprocess.run(['/usr/bin/systemd-tmpfiles', '--create', CONFIG],
                   check=True, timeout=15, capture_output=True, text=True)


def main():
    import fcntl
    if os.getuid() != 0 or os.environ.get('WSL_DISTRO_NAME') != 'EBase-Sandboxes':
        raise RuntimeError('Dedicated distro root required')
    # Only run during inactive maintenance. Do not operate on unrelated tmpfiles.
    state = subprocess.run(['/usr/bin/systemctl', 'show', 'e-base-sandboxd.service',
        '-p', 'ActiveState', '--value'], check=True, capture_output=True, text=True, timeout=10).stdout.strip()
    if state != 'inactive':
        raise RuntimeError('Inactive maintenance service required')
    try:
        before = identity()
    except FileNotFoundError:
        before = None
    create()
    first = identity()
    if before is not None and before != first:
        raise RuntimeError('Lock inode changed')
    # Root opens read-only, avoiding O_CREAT against fleet-owned sticky /tmp.
    with LOCK.open('rb') as owner:
        fcntl.flock(owner.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        create()
        if identity() != first:
            raise RuntimeError('Held lock inode changed')
        with LOCK.open('rb') as contender:
            try:
                fcntl.flock(contender.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                pass
            else:
                raise RuntimeError('Held lock failed to exclude second descriptor')
    with LOCK.open('rb') as released:
        fcntl.flock(released.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    print(json.dumps({'schema': 1, 'created_if_absent': before is None,
        'device': first[0], 'inode': first[1], 'repeated_create_preserved_inode': True,
        'held_lock_excluded_contender': True, 'reacquired_after_release': True,
        'daemon_started': False, 'reboot_verified': False}))


if __name__ == '__main__':
    main()
