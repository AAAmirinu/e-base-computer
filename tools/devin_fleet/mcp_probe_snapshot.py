"""Bounded private probe evidence reads. Not a process-stop attestation."""
import os
import re
import stat

from mcp_probe_binding import ARTIFACTS, digest
from mcp_probe_reservation import _private_directory


def _stamp(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _read(parent, name, limit):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid()
                or before.st_nlink != 1 or stat.S_IMODE(before.st_mode) != 0o600
                or before.st_size > limit):
            raise ValueError('Bounded private regular evidence required')
        with os.fdopen(os.dup(fd), 'rb') as stream:
            raw = stream.read(limit + 1)
        after = os.fstat(fd)
        linked = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if len(raw) != before.st_size or _stamp(before) != _stamp(after) or _stamp(after) != _stamp(linked):
            raise ValueError('Evidence changed while reading')
        return raw, [before.st_dev, before.st_ino]
    finally:
        os.close(fd)


def snapshot(work, reservation, *, stage):
    """Caller must serialize mutation and stop CLI/children before after-stage."""
    work = str(work)
    if re.fullmatch(r'/tmp/e-base-mcp-probe-[a-z0-9_]{8}', work) is None or stage not in ('before', 'after'):
        raise ValueError('Fixed probe work and stage required')
    expected = reservation.get('input_sha256') if type(reservation) is dict else None
    identity = reservation.get('audit_identity') if type(reservation) is dict else None
    if (type(expected) is not dict or set(expected) != ARTIFACTS
            or type(identity) is not list or len(identity) != 2
            or any(type(n) is not int or n < 0 for n in identity)):
        raise ValueError('Complete reserved inputs and audit inode required')
    root = _private_directory(work)
    config = git = None
    try:
        config = os.open('.devin', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
        meta = os.fstat(config)
        if meta.st_uid != os.getuid() or stat.S_IMODE(meta.st_mode) != 0o700:
            raise ValueError('Private MCP configuration directory required')
        if set(os.listdir(config))!={'mcp_config.json'}:
            raise ValueError('Unexpected project override')
        git=os.open('.git',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=root)
        meta=os.fstat(git)
        if meta.st_uid!=os.getuid() or stat.S_IMODE(meta.st_mode)!=0o700 or set(os.listdir(git))!={'HEAD','config','objects','refs'}:
            raise ValueError('Fixed private Git root required')
        for directory in ('objects','refs'):
            child=os.open(directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=git)
            try:
                info=os.fstat(child)
                if info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o700 or os.listdir(child):
                    raise ValueError('Empty private Git directory required')
                if _stamp(info)!=_stamp(os.stat(directory,dir_fd=git,follow_symlinks=False)):
                    raise ValueError('Git directory changed')
            finally: os.close(child)
        inputs = {}
        for name in sorted(ARTIFACTS):
            raw, _ = _read(config if name.startswith('.devin/') else git if name.startswith('.git/') else root, name.split('/')[-1], 1048576)
            if digest(raw) != expected[name]:
                raise ValueError('Reserved input changed')
            inputs[name] = raw
        audit, observed_identity = _read(root, 'fixture-events.log', 4096)
        if observed_identity != identity:
            raise ValueError('Reserved audit replaced')
        exported = None
        if stage == 'before':
            if audit:
                raise ValueError('Audit already used')
            try:
                os.stat('export.json', dir_fd=root, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise ValueError('Export already exists')
        else:
            exported, _ = _read(root, 'export.json', 1048576)
            if not exported:
                raise ValueError('Empty export')
        # Recheck path identities so renamed private directories cannot redirect launch.
        if _stamp(os.fstat(config)) != _stamp(os.stat('.devin', dir_fd=root, follow_symlinks=False)):
            raise ValueError('Configuration directory changed')
        if _stamp(os.fstat(git)) != _stamp(os.stat('.git', dir_fd=root, follow_symlinks=False)):
            raise ValueError('Git root changed')
        if _stamp(os.fstat(root)) != _stamp(os.stat(work, follow_symlinks=False)):
            raise ValueError('Work directory changed')
        return dict(inputs=inputs, audit_raw=audit, audit_identity=observed_identity, export_raw=exported)
    finally:
        if git is not None:
            os.close(git)
        if config is not None:
            os.close(config)
        os.close(root)
