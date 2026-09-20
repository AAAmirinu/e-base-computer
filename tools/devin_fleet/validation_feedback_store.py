"""Durably retain failed-validation feedback; never deliver, clear or execute it."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from durable import _sync_directory
from validation_failure_feedback import build_feedback
from validation_dispatch_receipt import _pairs
from validation_snapshot_input import _directory, _file, load_capture, load_snapshot, digest_argument


def persist_feedback(directory, feedback, *, filename='failure-feedback.json'):
    """Caller serializes with fleet lock. Partial evidence is preserved, not repaired.

    Exclusive creation prevents replacement. A crash during writing leaves a
    detectable conflicting file; a repeat of complete identical bytes fsyncs
    again before acknowledging durability. No consumer may trust existence alone.
    """
    directory = Path(directory)
    _directory(directory)
    if filename not in ('failure-feedback.json', 'failure-resolution.json',
                         'harness-failure-resolution.json'):
        raise ValueError('Unknown evidence filename')
    payload = (json.dumps(feedback, sort_keys=True, ensure_ascii=True,
                          allow_nan=False, separators=(',', ':')) + '\n').encode()
    if len(payload) > 8 * 1024 * 1024:
        raise ValueError('Feedback exceeds bound')
    path = directory / filename
    created = False
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    except FileExistsError:
        if path.is_symlink():
            raise ValueError('Linked feedback refused')
        fd = os.open(path, os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
        with os.fdopen(fd, 'r+b') as stream:
            meta = os.fstat(stream.fileno())
            if (not stat.S_ISREG(meta.st_mode) or meta.st_nlink != 1 or
                    meta.st_size > 8 * 1024 * 1024 or
                    (os.name == 'posix' and (meta.st_uid != os.getuid() or meta.st_mode & 0o077))):
                raise ValueError('Unsafe existing feedback')
            if stream.read(8 * 1024 * 1024 + 1) != payload:
                raise ValueError('Existing feedback is partial or conflicting; preserve and inspect')
            os.fsync(stream.fileno())
    else:
        created = True
        with os.fdopen(fd, 'wb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    _sync_directory(directory)
    return {'path': str(path), 'sha256': hashlib.sha256(payload).hexdigest(),
            'created': created, 'delivered': False, 'hold_cleared': False}


def main():
    import argparse
    import fcntl
    from validation_snapshot_dispatch import inventory, UUID
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dispatch', required=True)
    parser.add_argument('--snapshot', required=True)
    parser.add_argument('--manifest-sha256', required=True, type=digest_argument)
    args = parser.parse_args()
    if os.environ.get('WSL_DISTRO_NAME') != 'EBase-Sandboxes' or os.getuid() != 1000:
        raise RuntimeError('Dedicated distro required')
    root = Path('/home/fleet/controller-validation')
    dispatch, snapshot = Path(args.dispatch), Path(args.snapshot)
    if dispatch.parent != root or not re.fullmatch('dispatch-[0-9a-f]{32}', dispatch.name):
        raise ValueError('Dedicated dispatch directory required')
    for path in (dispatch, snapshot):
        if root not in path.parents or path.resolve() != path:
            raise ValueError('Dedicated unlinked input required')
        _directory(path)
        for parent in path.parents:
            metadata = parent.stat()
            if metadata.st_uid not in (0, os.getuid()) or metadata.st_mode & 0o022:
                raise ValueError('Unprotected ancestor')
    with open('/tmp/e-base-devin-fleet-global.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _, _, manifest = load_snapshot(snapshot, args.manifest_sha256)
        roles = json.loads(_file(root / 'sandbox-registry.json', 1024 * 1024),
                           object_pairs_hook=_pairs)['roles']
        capture = load_capture(snapshot.parent / 'capture.json', snapshot,
                               args.manifest_sha256, manifest, roles)
        values, vm = inventory()
        if any(v['status'] != 'stopped' for v in values):
            raise RuntimeError('All VMs must remain stopped')
        feedback = build_feedback(_file(dispatch / 'dispatch.json', 8 * 1024 * 1024),
            _file(dispatch / 'stdout.log', 8 * 1024 * 1024), capture_evidence=capture,
            expected_vm=UUID, live_vm=vm)
        print(json.dumps(persist_feedback(dispatch, feedback)), flush=True)


if __name__ == '__main__':
    main()
