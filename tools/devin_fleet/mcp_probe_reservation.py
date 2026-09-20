"""Trusted guest supervisor preparation; never launches a CLI or opens network.

The fixed claim survives failure and is never automatically reset. Call only in
the dedicated guest, with a private state directory and trusted input builder.
"""
import json
import os
from pathlib import Path
import secrets
import stat
import tempfile

from mcp_probe_binding import ARTIFACTS, digest

CLAIM = 'mcp-denial-v1'


def _private_directory(path):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('Absolute private directory required')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in path.parts[1:]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError('Owned mode-700 directory required')
        return fd
    except BaseException:
        os.close(fd)
        raise


def _exclusive_file(parent, name, raw):
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                 0o600, dir_fd=parent)
    try:
        remaining = memoryview(raw)
        while remaining:
            count = os.write(fd, remaining)
            if count <= 0:
                raise OSError('Incomplete reserved input')
            remaining = remaining[count:]
        os.fsync(fd)
        info = os.fstat(fd)
        return [info.st_dev, info.st_ino]
    finally:
        os.close(fd)


def prepare_attempt(state_directory, build_inputs, *, previous_sessions):
    """Consume one durable claim before invoking a trusted configuration builder.

Any existing claim, including an empty or partial one, refuses re-entry. A
returned reservation proves preparation only, not execution or process cleanup.
    """
    if (not callable(build_inputs) or type(previous_sessions) is not list
            or len(previous_sessions) > 4096
            or any(type(s) is not str or not 1 <= len(s) <= 128 for s in previous_sessions)):
        raise ValueError('Trusted builder and bounded session inventory required')
    previous_sessions = list(previous_sessions)
    state_fd = _private_directory(state_directory)
    claim_fd = work_fd = config_fd = git_fd = None
    try:
        os.mkdir(CLAIM, 0o700, dir_fd=state_fd)
        os.fsync(state_fd)
        claim_fd = os.open(CLAIM, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=state_fd)
        nonce = secrets.token_hex(16)
        work = Path(tempfile.mkdtemp(prefix='e-base-mcp-probe-', dir='/tmp'))
        work_fd = _private_directory(work)
        # Persist the locator before preparing anything that could be executed.
        locator = json.dumps({'nonce': nonce, 'work': str(work), 'phase': 'preparing'}).encode()
        _exclusive_file(claim_fd, 'attempt.json', locator)
        os.fsync(claim_fd)
        identity = _exclusive_file(work_fd, 'fixture-events.log', b'')
        inputs = build_inputs(work, nonce, tuple(identity))
        if type(inputs) is not dict or set(inputs) != ARTIFACTS:
            raise ValueError('Exact fixed prepared input set required')
        hashes = {name: digest(raw) for name, raw in inputs.items()}
        os.mkdir('.devin', 0o700, dir_fd=work_fd)
        config_fd = os.open('.devin', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=work_fd)
        os.mkdir('.git', 0o700, dir_fd=work_fd)
        git_fd = os.open('.git', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=work_fd)
        for directory in ('objects','refs'):
            os.mkdir(directory,0o700,dir_fd=git_fd)
            child=os.open(directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=git_fd)
            try: os.fsync(child)
            finally: os.close(child)
        for name, raw in inputs.items():
            _exclusive_file(config_fd if name.startswith('.devin/') else git_fd if name.startswith('.git/') else work_fd,
                            name.split('/')[-1], raw)
        os.fsync(config_fd)
        os.fsync(git_fd)
        os.fsync(work_fd)
        tmp_fd = os.open('/tmp', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(tmp_fd)
        finally:
            os.close(tmp_fd)
        reservation = dict(schema=1, nonce=nonce, phase='reserved', input_sha256=hashes,
                           audit_identity=identity, previous_sessions=previous_sessions)
        # Validate the actual on-disk inputs before publishing a ready reservation.
        # Import locally because snapshot uses the private-directory helper above.
        from mcp_probe_snapshot import snapshot
        snapshot(work, reservation, stage='before')
        _exclusive_file(claim_fd, 'reservation.json', json.dumps(reservation, allow_nan=False).encode())
        os.fsync(claim_fd)
        return work, reservation
    finally:
        for fd in (git_fd, config_fd, work_fd, claim_fd, state_fd):
            if fd is not None:
                os.close(fd)
