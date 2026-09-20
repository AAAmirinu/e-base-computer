"""Capture a bounded source-only snapshot for a separate credential-free VM.

No archive extraction, file materialization, tests, Git staging or commit here.
Caller must own a quiescent role lease and bind the returned manifest to validation.
"""
import hashlib
import json
from pathlib import Path

from durable import _atomic_bytes, _sync_directory

import fleet
from sandbox_snapshot_receiver import validate_snapshot


def _inventory(text):
    if not isinstance(text, str) or (text and not text.endswith('\0')):
        raise ValueError('Malformed NUL-delimited source inventory')
    paths = text[:-1].split('\0') if text else []
    if len(paths) != len(set(paths)):
        raise ValueError('Duplicate source inventory path')
    for path in paths:
        if (not path or path.startswith('/') or '\\' in path or ':' in path or
                any(part in ('', '.', '..') for part in path.split('/'))):
            raise ValueError('Unsafe source path')
    return paths


def _unchanged(repo, expected):
    if (fleet.sha(repo) != expected['base'] or
            sorted(fleet.changes(repo)) != sorted(expected['changed']) or
            fleet.fingerprints(repo, expected['changed']) != expected['fingerprints']):
        raise RuntimeError('Source no longer matches model-phase checkpoint')


def capture_source_snapshot(repo, expected):
    _unchanged(repo, expected)
    tracked = _inventory(repo.git('ls-files', '-z'))
    others = _inventory(repo.git('ls-files', '--others', '--exclude-standard', '-z'))
    if any(p == '.fleet' or p.startswith('.fleet/') for p in tracked):
        raise ValueError('Tracked controller metadata is not source')
    others = [p for p in others if p != '.fleet' and not p.startswith('.fleet/')]
    paths = sorted(set(tracked) | set(others))
    if len(paths) > 2048:
        raise ValueError('Source file count exceeds snapshot bound')
    files, blobs, total = [], {}, 0
    for path in paths:
        if (any(part.lower() in ('.git', '.devin', '.fleet') for part in path.split('/')) or
                path.split('/')[0].lower() in ('private_materials', '.env')):
            raise ValueError('Private or repository metadata is not validation source')
        kind = repo.path_kind(path)
        if kind == 'missing' and path in tracked:
            continue
        if kind != 'regular':
            raise RuntimeError('Linked, missing or special source file refused')
        value = repo.snapshot_file(path, max_bytes=1024 * 1024)
        data, mode = value['data'], value['mode']
        if not isinstance(data, bytes) or len(data) > 1024 * 1024 or mode not in ('100644', '100755'):
            raise ValueError('Invalid source file snapshot')
        total += len(data)
        if total > 16 * 1024 * 1024:
            raise ValueError('Source bytes exceed snapshot bound')
        digest = hashlib.sha256(data).hexdigest()
        blobs[digest] = data
        files.append({'path': path, 'mode': mode, 'sha256': digest, 'size': len(data)})
    # A stopped model is required, and unexpected edits abort capture. This is
    # not a filesystem-atomic snapshot against another writer in the same VM.
    _unchanged(repo, expected)
    if tracked != _inventory(repo.git('ls-files', '-z')):
        raise RuntimeError('Tracked source inventory changed during capture')
    manifest = {'schema': 1, 'base': expected['base'], 'files': files}
    canonical = json.dumps(manifest, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    digest = hashlib.sha256(canonical).hexdigest()
    validate_snapshot(canonical, digest, blobs)
    return {'manifest': manifest, 'manifest_sha256': digest, 'blobs': blobs}


def persist_source_snapshot(directory, snapshot):
    """Write inert content-addressed files only, never materialize source paths."""
    canonical = json.dumps(snapshot['manifest'], sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    if hashlib.sha256(canonical).hexdigest() != snapshot['manifest_sha256']:
        raise ValueError('Snapshot manifest digest mismatch')
    validate_snapshot(canonical, snapshot['manifest_sha256'], snapshot['blobs'])
    for digest, data in snapshot['blobs'].items():
        if not isinstance(data, bytes) or hashlib.sha256(data).hexdigest() != digest:
            raise ValueError('Snapshot blob digest mismatch')
    for entry in snapshot['manifest']['files']:
        data = snapshot['blobs'][entry['sha256']]
        if len(data) != entry['size']:
            raise ValueError('Snapshot blob length mismatch')
    directory = Path(directory)
    if not directory.is_absolute():
        raise ValueError('Absolute private snapshot output required')
    directory.mkdir(mode=0o700)
    _sync_directory(directory.parent)
    blobs = directory / 'blobs'
    blobs.mkdir(mode=0o700)
    _sync_directory(directory)
    for digest, data in snapshot['blobs'].items():
        _atomic_bytes(blobs / digest, data)
    # Manifest last: partial blob output is not a complete snapshot.
    _atomic_bytes(directory / 'manifest.json', canonical)
