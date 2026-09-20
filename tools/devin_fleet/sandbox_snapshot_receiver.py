"""Strict source-snapshot admission and Linux-only inert materialization.

No source is imported or executed. This is not a container isolation check.
The caller must provide a trusted, private parent directory and verified VM
ownership. Failed partial output is retained, never reused or marked complete.
"""
import hashlib
import json
import os
import re
import sys


MAX_MANIFEST = 1024 * 1024
MAX_FILES = 2048
MAX_FILE = 1024 * 1024
MAX_TOTAL = 16 * 1024 * 1024


def _hex(value, length):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{%d}' % length, value) is not None


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate manifest field')
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError('Non-integer manifest number')


def validate_snapshot(raw, expected_digest, blobs):
    """Validate exact canonical manifest and bounded, complete blob dictionary."""
    if not isinstance(raw, bytes) or len(raw) > MAX_MANIFEST:
        raise ValueError('Invalid manifest bytes or size')
    if not _hex(expected_digest, 64) or hashlib.sha256(raw).hexdigest() != expected_digest:
        raise ValueError('Manifest digest mismatch')
    try:
        manifest = json.loads(raw.decode('utf-8'), object_pairs_hook=_object,
                              parse_float=_reject_constant, parse_constant=_reject_constant)
    except (UnicodeError, RecursionError, ValueError) as error:
        raise ValueError('Malformed manifest') from error
    if (not isinstance(manifest, dict) or set(manifest) != {'schema', 'base', 'files'} or
            type(manifest['schema']) is not int or manifest['schema'] != 1 or
            not _hex(manifest['base'], 40) or not isinstance(manifest['files'], list) or
            len(manifest['files']) > MAX_FILES):
        raise ValueError('Unsupported manifest schema')
    paths, required, total = [], {}, 0
    for entry in manifest['files']:
        if not isinstance(entry, dict) or set(entry) != {'path', 'mode', 'sha256', 'size'}:
            raise ValueError('Invalid source entry')
        path = entry['path']
        if not isinstance(path, str):
            raise ValueError('Invalid source path')
        parts = path.split('/')
        if (not path or len(parts) > 128 or '\\' in path or ':' in path or
                any(ord(char) < 32 or ord(char) == 127 for char in path) or
                any(part in ('', '.', '..') for part in parts) or
                any(part.lower() in ('.git', '.devin', '.fleet') for part in parts) or
                parts[0].lower() in ('private_materials', '.env')):
            raise ValueError('Unsafe source path')
        try:
            if len(path.encode('utf-8')) > 4095 or any(len(p.encode('utf-8')) > 255 for p in parts):
                raise ValueError('Source path too long')
        except UnicodeError as error:
            raise ValueError('Invalid source path encoding') from error
        if (entry['mode'] not in ('100644', '100755') or not _hex(entry['sha256'], 64) or
                type(entry['size']) is not int or not 0 <= entry['size'] <= MAX_FILE):
            raise ValueError('Invalid source metadata')
        total += entry['size']
        if total > MAX_TOTAL:
            raise ValueError('Source snapshot too large')
        digest = entry['sha256']
        if digest in required and required[digest] != entry['size']:
            raise ValueError('Conflicting blob sizes')
        required[digest] = entry['size']
        paths.append(path)
    if paths != sorted(set(paths)):
        raise ValueError('Source paths must be unique and sorted')
    path_set = set(paths)
    for path in paths:
        parts = path.split('/')
        if any('/'.join(parts[:i]) in path_set for i in range(1, len(parts))):
            raise ValueError('Source file-directory collision')
    if not isinstance(blobs, dict) or set(blobs) != set(required):
        raise ValueError('Missing or extraneous source blobs')
    for digest, size in required.items():
        data = blobs[digest]
        if not isinstance(data, bytes) or len(data) != size or hashlib.sha256(data).hexdigest() != digest:
            raise ValueError('Source blob mismatch')
    canonical = json.dumps(manifest, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    if canonical != raw:
        raise ValueError('Non-canonical manifest')
    return manifest


def materialize_snapshot(parent, name, raw, expected_digest, blobs):
    """Create a fresh Linux directory using dirfds, exclusive files, no links.

    Parent and its ancestors must be owned/protected by the trusted caller;
    opening each ancestor without following links prevents accidental aliasing.
    Returned receipt is emitted only after all file and directory fsyncs.
    It proves bytes/modes were written, not permission to run project code.
    """
    manifest = validate_snapshot(raw, expected_digest, blobs)
    if sys.platform != 'linux' or not hasattr(os, 'O_NOFOLLOW'):
        raise RuntimeError('Linux guest materialization required')
    if not isinstance(parent, str) or not parent.startswith('/') or any(p in ('.', '..') for p in parent.split('/')):
        raise ValueError('Absolute trusted parent required')
    if not isinstance(name, str) or re.fullmatch('[a-zA-Z0-9][a-zA-Z0-9_-]{0,95}', name) is None:
        raise ValueError('Invalid fresh output name')
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    parent_fd = os.open('/', flags)
    try:
        for part in filter(None, parent.split('/')):
            next_fd = os.open(part, flags, dir_fd=parent_fd)
            os.close(parent_fd)
            parent_fd = next_fd
        os.mkdir(name, 0o700, dir_fd=parent_fd)
        os.fsync(parent_fd)
        root_fd = os.open(name, flags, dir_fd=parent_fd)
        try:
            for entry in manifest['files']:
                directory_fd = os.dup(root_fd)
                try:
                    parts = entry['path'].split('/')
                    for part in parts[:-1]:
                        try:
                            os.mkdir(part, 0o700, dir_fd=directory_fd)
                            os.fsync(directory_fd)
                        except FileExistsError:
                            pass
                        next_fd = os.open(part, flags, dir_fd=directory_fd)
                        os.close(directory_fd)
                        directory_fd = next_fd
                    file_fd = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                      0o600, dir_fd=directory_fd)
                    try:
                        view = memoryview(blobs[entry['sha256']])
                        while view:
                            count = os.write(file_fd, view)
                            if count <= 0:
                                raise OSError('Incomplete source write')
                            view = view[count:]
                        os.fchmod(file_fd, 0o755 if entry['mode'] == '100755' else 0o644)
                        os.fsync(file_fd)
                    finally:
                        os.close(file_fd)
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            os.fsync(root_fd)
        finally:
            os.close(root_fd)
    finally:
        os.close(parent_fd)
    return {'schema': 1, 'manifest_sha256': expected_digest, 'base': manifest['base'],
            'file_count': len(manifest['files']), 'source_executed': False}
