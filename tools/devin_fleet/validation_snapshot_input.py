"""Load only bounded inert snapshot bytes from a trusted private directory."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import uuid
from sandbox_snapshot_receiver import validate_snapshot
from validation_dispatch_receipt import _pairs


def digest_argument(value):
    if not isinstance(value, str) or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise ValueError('Explicit lowercase manifest SHA256 required')
    return value


def _directory(path):
    if not path.is_absolute() or path.resolve() != path:
        raise ValueError('Absolute unlinked snapshot directory required')
    meta = path.stat()
    if not stat.S_ISDIR(meta.st_mode):
        raise ValueError('Snapshot directory required')
    if os.name == 'posix' and (meta.st_uid != os.getuid() or meta.st_mode & 0o077):
        raise ValueError('Snapshot directory must be private and caller-owned')


def _file(path, limit):
    if path.is_symlink():
        raise ValueError('Linked snapshot file refused')
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(fd, 'rb') as stream:
        meta = os.fstat(stream.fileno())
        if not stat.S_ISREG(meta.st_mode) or meta.st_nlink != 1 or meta.st_size > limit:
            raise ValueError('Unsafe snapshot file or size')
        if os.name == 'posix' and (meta.st_uid != os.getuid() or meta.st_mode & 0o022):
            raise ValueError('Unprotected snapshot file')
        data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError('Snapshot file exceeds bound')
        return data


def load_snapshot(directory, expected_digest):
    digest_argument(expected_digest)
    directory = Path(directory)
    _directory(directory)
    _directory(directory / 'blobs')
    raw = _file(directory / 'manifest.json', 1024 * 1024)
    if hashlib.sha256(raw).hexdigest() != expected_digest:
        raise ValueError('Caller manifest digest mismatch')
    manifest = json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs)
    if not isinstance(manifest, dict) or not isinstance(manifest.get('files'), list) or len(manifest['files']) > 2048:
        raise ValueError('Invalid bounded manifest inventory')
    required = set()
    for entry in manifest['files']:
        if not isinstance(entry, dict):
            raise ValueError('Invalid source entry')
        required.add(digest_argument(entry.get('sha256')))
    actual = set()
    with os.scandir(directory / 'blobs') as items:
        for item in items:
            if len(actual) >= 2048 or not item.is_file(follow_symlinks=False):
                raise ValueError('Invalid blob inventory')
            actual.add(item.name)
    if actual != required:
        raise ValueError('Missing or extraneous blob inventory')
    blobs, total = {}, 0
    for digest in sorted(required):
        data = _file(directory / 'blobs' / digest, 1024 * 1024)
        total += len(data)
        if total > 16 * 1024 * 1024:
            raise ValueError('Snapshot bytes exceed bound')
        blobs[digest] = data
    validate_snapshot(raw, expected_digest, blobs)
    return raw, blobs, manifest


def load_capture(path, snapshot_directory, digest, manifest, roles):
    """Bind controller-owned capture provenance, not source/model assertions."""
    path, snapshot_directory = Path(path), Path(snapshot_directory)
    if path != snapshot_directory.parent / 'capture.json' or path.resolve() != path:
        raise ValueError('Capture must accompany the selected snapshot')
    _directory(path.parent)
    raw = _file(path, 1024 * 1024)
    value = json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs)
    if not isinstance(value, dict):
        raise ValueError('Invalid capture receipt')
    role = value.get('role')
    if not isinstance(role, str) or role not in roles or value.get('sandbox_id') != roles[role]['id']:
        raise ValueError('Capture role or VM registration mismatch')
    checkpoint = value.get('source_checkpoint')
    if (type(value.get('schema')) is not int or value['schema'] != 1 or
            value.get('manifest_sha256') != digest or value.get('base') != manifest['base'] or
            value.get('snapshot_directory') != str(snapshot_directory) or
            value.get('source_executed') is not False or value.get('source_vm_stopped') is not True or
            not isinstance(checkpoint, dict) or checkpoint.get('base') != manifest['base'] or
            not isinstance(checkpoint.get('changed'), list) or not isinstance(checkpoint.get('fingerprints'), dict)):
        raise ValueError('Capture snapshot/checkpoint mismatch')
    files = {entry['path']: entry for entry in manifest['files']}
    changed = checkpoint['changed']
    if (any(not isinstance(p, str) or not p or p.startswith('/') or '\\' in p or ':' in p or
            any(part in ('', '.', '..') for part in p.split('/')) for p in changed) or
            len(set(changed)) != len(changed) or set(checkpoint['fingerprints']) != set(changed)):
        raise ValueError('Invalid changed-path inventory')
    for path, fingerprint in checkpoint['fingerprints'].items():
        if fingerprint is None:
            if path in files:
                raise ValueError('Deleted checkpoint file exists in snapshot')
        elif path not in files or fingerprint != files[path]['sha256']:
            raise ValueError('Changed-file fingerprint mismatch')
    counts = {'file_count': len(files), 'source_bytes': sum(f['size'] for f in files.values()),
              'blob_count': len({f['sha256'] for f in files.values()})}
    if any(type(value.get(k)) is not int or value[k] != expected for k, expected in counts.items()):
        raise ValueError('Capture counts mismatch')
    return {'capture_sha256': hashlib.sha256(raw).hexdigest(), 'capture': value}


def load_turn_binding(path, capture_evidence, *, expected_epoch):
    """Bind an explicit controller turn to its already validated source capture.

    This authorizes neither model resume nor candidate acceptance. Incomplete
    records, maintenance-only captures and mismatched operations are rejected.
    """
    capture = capture_evidence['capture']
    if (not isinstance(expected_epoch, str) or str(uuid.UUID(expected_epoch)) != expected_epoch
            or capture.get('migration_epoch') != expected_epoch):
        raise ValueError('Capture is not from the current registered epoch')
    path = Path(path)
    expected = Path(capture['snapshot_directory']).parent / 'turn.json'
    if path != expected or path.resolve() != path:
        raise ValueError('Turn must accompany the selected capture')
    _directory(path.parent)
    raw = _file(path, 1024 * 1024)
    turn = json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs)
    if (not isinstance(turn, dict) or type(turn.get('schema')) is not int or turn['schema'] != 1
            or turn.get('phase') != 'awaiting_validation'
            or turn.get('validation_passed') is not False or turn.get('committed') is not False):
        raise ValueError('Turn is not awaiting separate validation')
    for key in ('operation_id', 'migration_epoch', 'sequence', 'role', 'sandbox_id'):
        if key not in capture or turn.get(key) != capture[key]:
            raise ValueError('Turn/capture identity mismatch')
    if (not isinstance(turn.get('operation_id'), str)
            or re.fullmatch('[0-9a-f]{32}', turn['operation_id']) is None
            or type(turn.get('sequence')) is not int or turn['sequence'] < 0
            or type(capture.get('sequence')) is not int):
        raise ValueError('Invalid turn operation or sequence')
    for key in ('migration_epoch', 'sandbox_id'):
        if not isinstance(turn[key], str) or str(uuid.UUID(turn[key])) != turn[key]:
            raise ValueError('Invalid canonical turn identity')
    if (turn.get('snapshot') != capture.get('source_checkpoint')
            or turn['snapshot'].get('manifest_sha256') != capture['manifest_sha256']
            or turn.get('base') != capture['base']):
        raise ValueError('Turn/capture snapshot mismatch')
    return {'turn_sha256': hashlib.sha256(raw).hexdigest(),
            'capture_sha256': capture_evidence['capture_sha256'],
            **{key: turn[key] for key in ('operation_id', 'migration_epoch', 'sequence', 'role', 'sandbox_id')},
            'manifest_sha256': capture['manifest_sha256'], 'base': capture['base']}
