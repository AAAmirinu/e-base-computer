"""Admission fence for unresolved outer dispatches; caller holds fleet lock."""
import json
import os
from pathlib import Path
import re
import stat
from validation_dispatch_receipt import _pairs
from validation_dispatch_recovery import inspect_record
from validation_probe_closure import verify_closure
from validation_failure_resolution import verify_resolution
from validation_harness_failure_resolution import verify_resolution as verify_harness_resolution


def _read(path):
    if path.is_symlink():
        raise ValueError('Linked evidence refused')
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(fd, 'rb') as stream:
        metadata = os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or metadata.st_size > 8 * 1024 * 1024:
            raise ValueError('Unsafe evidence file')
        if os.name == 'posix' and (metadata.st_uid != os.getuid() or metadata.st_mode & 0o022):
            raise ValueError('Unprotected evidence file')
        return stream.read(8 * 1024 * 1024 + 1)


def unresolved_dispatches(root, expected_vm, live_vm):
    """Read-only list. A complete phase alone never clears a prior dispatch.

    The root is trusted and protected by the caller; inspection does not confer
    test acceptance and does not mutate, archive, clear or replay old records.
    """
    root = Path(root)
    if not root.is_absolute() or root.resolve() != root:
        raise ValueError('Absolute unlinked history root required')
    metadata = root.stat()
    if os.name == 'posix' and (metadata.st_uid != os.getuid() or metadata.st_mode & 0o022):
        raise ValueError('History root must be caller-owned and protected')
    entries = []
    with os.scandir(root) as iterator:
        for entry in iterator:
            if not entry.name.startswith('dispatch-'):
                continue
            if len(entries) >= 1024:
                raise RuntimeError('Dispatch history exceeds inspection bound')
            entries.append(entry)
    holds = []
    for entry in sorted(entries, key=lambda e: e.name):
        path = root / entry.name
        try:
            if not entry.is_dir(follow_symlinks=False) or re.fullmatch('dispatch-[0-9a-f]{32}', entry.name) is None:
                raise ValueError('Invalid dispatch directory')
            metadata = entry.stat(follow_symlinks=False)
            if os.name == 'posix' and (metadata.st_uid != os.getuid() or metadata.st_mode & 0o077):
                raise ValueError('Dispatch directory must be private and caller-owned')
            raw = _read(path / 'dispatch.json')
            journal = json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs)
            if not isinstance(journal, dict):
                raise ValueError('Invalid dispatch record')
            if journal.get('phase') != 'complete':
                if os.path.lexists(path / 'harness-failure-resolution.json'):
                    if (os.path.lexists(path / 'failure-resolution.json')
                            or os.path.lexists(path / 'closure.json')):
                        raise ValueError('Conflicting resolution types')
                    verify_harness_resolution(raw, _read(path / 'stdout.log'),
                        _read(path / 'harness-failure-resolution.json'))
                    continue
                if os.path.lexists(path / 'failure-resolution.json'):
                    if os.path.lexists(path / 'closure.json'):
                        raise ValueError('Conflicting resolution types')
                    verify_resolution(raw, _read(path / 'stdout.log'),
                        _read(path / 'failure-feedback.json'), _read(path / 'feedback-delivery.json'),
                        _read(path / 'failure-resolution.json'), entry.name.removeprefix('dispatch-'), expected_vm, live_vm)
                    continue
                if (path / 'closure.json').exists():
                    verify_closure(raw, _read(path / 'crash-evidence.json'), _read(path / 'closure.json'),
                        entry.name.removeprefix('dispatch-'), expected_vm, live_vm)
                    continue
                holds.append({'directory': str(path), 'reason': 'incomplete_dispatch_phase'})
                continue
            fields = {'manifest_sha256': '[0-9a-f]{64}', 'image_id': 'sha256:[0-9a-f]{64}', 'base': '[0-9a-f]{40}'}
            if any(not isinstance(journal.get(k), str) or not re.fullmatch(pattern, journal[k]) for k, pattern in fields.items()):
                raise ValueError('Invalid historical identity')
            outcome = inspect_record(raw, _read(path / 'stdout.log'), digest=journal['manifest_sha256'],
                image=journal['image_id'], base=journal['base'], expected_vm=expected_vm, live_vm=live_vm)
            if outcome['outcome'] != 'verified_completed_dispatch':
                holds.append({'directory': str(path), 'reason': outcome['reason']})
        except (OSError, ValueError, TypeError, RecursionError):
            holds.append({'directory': str(path), 'reason': 'missing_or_invalid_evidence'})
    return holds
