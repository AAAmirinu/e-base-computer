"""Durable per-role exclusion across controller crashes; never auto-release.

The reservation is not proof that a VM is stopped or that output is accepted.
Incomplete writes remain a fence. Resolution requires a separate inspected
workflow; neither model output nor restarting this process can clear it.
"""
import json
import hashlib
import os
from pathlib import Path
import stat
import uuid

from durable import _sync_directory

ROLES = frozenset(('machine', 'coordinator', 'toolchain', 'kernel', 'stdlib',
                   'storage', 'services', 'applications', 'devtools', 'assurance'))


def _reservation(raw, role):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate reservation key')
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=unique)
    keys = {'schema', 'operation_id', 'migration_epoch', 'role', 'sequence',
            'sandbox_id', 'run_directory', 'state', 'automatic_resume'}
    if (not isinstance(value, dict) or set(value) != keys or
            type(value['schema']) is not int or value['schema'] != 1 or
            value['role'] != role or type(value['sequence']) is not int or value['sequence'] < 0 or
            value['state'] != 'unresolved' or value['automatic_resume'] is not False):
        raise ValueError('Invalid reservation schema')
    operation = value['operation_id']
    if (not isinstance(operation, str) or len(operation) != 32 or
            any(c not in '0123456789abcdef' for c in operation)):
        raise ValueError('Invalid operation identity')
    for key in ('migration_epoch', 'sandbox_id'):
        if not isinstance(value[key], str) or str(uuid.UUID(value[key])) != value[key]:
            raise ValueError('Canonical identity required')
    if (not isinstance(value['run_directory'], str) or
            not Path(value['run_directory']).is_absolute() or '\0' in value['run_directory'] or
            '..' in Path(value['run_directory']).parts):
        raise ValueError('Invalid recorded directory')
    return value


def inspect_turn_fences(controller_root, registration):
    """Report local evidence only. Never follow a recorded run_directory."""
    if (not isinstance(registration, dict) or not isinstance(registration.get('roles'), dict) or
            any(not isinstance(entry, dict) for entry in registration['roles'].values())):
        raise ValueError('Trusted role registration object required')
    root = Path(controller_root)
    if not root.is_absolute() or '..' in root.parts:
        raise ValueError('Absolute trusted controller root required')
    for parent in root.parents:
        _directory(parent)
    _directory(root, private=True)
    fences = root/'model-turn-fences'
    report = {'roles': {role: {'state': 'absent'} for role in sorted(ROLES)},
              'resume_available': False, 'runtime_state_observed': False}
    try:
        _directory(fences, private=True)
    except FileNotFoundError:
        return report
    for role in sorted(ROLES):
        path = fences/(role + '.json')
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        item = report['roles'][role] = {'state': 'invalid'}
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                getattr(info, 'st_file_attributes', 0) & 0x400 or
                (os.name != 'nt' and (info.st_uid != os.getuid() or info.st_mode & 0o077))):
            continue
        try:
            descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) |
                                 getattr(os, 'O_NONBLOCK', 0))
            with os.fdopen(descriptor, 'rb') as stream:
                opened = os.fstat(stream.fileno())
                if (not stat.S_ISREG(opened.st_mode) or
                        (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino)):
                    continue
                raw = stream.read(65537)
                after = os.fstat(stream.fileno())
            current = path.lstat()
            def stamp(value):
                # Windows lstat/fstat expose different legacy ctime semantics;
                # production Linux additionally checks inode change time.
                return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns,
                        value.st_ctime_ns if os.name != 'nt' else None)
            if len(raw) > 65536 or any(stamp(v) != stamp(info) for v in (opened, after, current)):
                continue
            item['sha256'] = hashlib.sha256(raw).hexdigest()
            value = _reservation(raw, role)
            matching = (registration.get('controller_root') == str(root) and
                        registration.get('migration_epoch') == value['migration_epoch'] and
                        registration.get('roles', {}).get(role, {}).get('id') == value['sandbox_id'])
            item['state'] = 'unresolved' if matching else 'identity_mismatch'
        except (ValueError, TypeError, OSError):
            # Opaque invalid state, never echo untrusted data/error strings.
            continue
    return report


def _directory(path, *, private=False):
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or
            getattr(info, 'st_file_attributes', 0) & 0x400):
        raise ValueError('Real controller directory required')
    if private and os.name != 'nt' and (info.st_uid != os.getuid() or info.st_mode & 0o077):
        raise ValueError('Private controller-owned directory required')


def reserve_turn(controller_root, receipt, run_directory):
    root, run = Path(controller_root), Path(run_directory)
    if not root.is_absolute() or '..' in root.parts or not run.is_absolute():
        raise ValueError('Absolute trusted controller paths required')
    if receipt.get('role') not in ROLES:
        raise ValueError('Fixed registered role required')
    for parent in root.parents:
        _directory(parent)
    _directory(root, private=True)
    fences = root / 'model-turn-fences'
    fences.mkdir(mode=0o700, exist_ok=True)
    _directory(fences, private=True)
    _sync_directory(root)
    path = fences / (receipt['role'] + '.json')
    value = {key: receipt[key] for key in ('schema', 'operation_id', 'migration_epoch',
                                         'role', 'sequence', 'sandbox_id')}
    value.update(run_directory=str(run), state='unresolved', automatic_resume=False)
    payload = (json.dumps(value, sort_keys=True) + '\n').encode('utf-8')
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY |
                             getattr(os, 'O_NOFOLLOW', 0), 0o600)
    except FileExistsError as exc:
        raise RuntimeError('Unresolved prior model turn; inspect before another attempt') from exc
    # Never unlink on error: a partial or empty reservation must also block retry.
    with os.fdopen(descriptor, 'wb') as output:
        output.write(payload)
        output.flush()
        os.fsync(output.fileno())
    _sync_directory(fences)
    return path
