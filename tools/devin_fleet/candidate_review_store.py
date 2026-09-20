"""Durable review queue insertion; no fence release, runtime resume, or publishing.

Call under the trusted controller's global lock. A partially created operation
directory is a recovery hold, never a reason to rebuild the candidate or retry.
"""
import hashlib
import json
import os
import re
from pathlib import Path
import sys

from candidate_evidence_binding import bind_turn_candidate
from durable import atomic_write_json, _sync_directory
from sandbox_turn_fence import _directory, _reservation
from validation_snapshot_input import _file, load_snapshot
from sandbox_snapshot import persist_source_snapshot
from validation_dispatch_receipt import _pairs
from turn_validation_result import same_json


def _exclusive_bytes(path, data):
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def record_candidate(controller_root, registration, binding, **evidence):
    if sys.platform != 'linux':
        raise RuntimeError('Dedicated Linux controller required')
    root = Path(controller_root)
    if (not root.is_absolute() or root.resolve() != root
            or registration.get('controller_root') != str(root)):
        raise ValueError('Registered private controller root required')
    for parent in root.parents:
        _directory(parent)
    _directory(root, private=True)
    verified = bind_turn_candidate(binding, registration, **evidence)
    fences = root/'model-turn-fences'
    _directory(fences, private=True)
    fence_path = fences/(binding['role']+'.json')
    fence_raw = _file(fence_path, 65536)
    reserved = _reservation(fence_raw, binding['role'])
    for key in ('operation_id', 'migration_epoch', 'role', 'sequence', 'sandbox_id'):
        if type(reserved[key]) is not type(binding[key]) or reserved[key] != binding[key]:
            raise ValueError('Candidate is not the unresolved reserved turn')
    queue = root/'candidate-review'
    queue.mkdir(mode=0o700, exist_ok=True)
    _directory(queue, private=True)
    _sync_directory(root)
    work = queue/binding['operation_id']
    # Exclusive directory is retained even when subsequent writes fail.
    work.mkdir(mode=0o700)
    _sync_directory(queue)
    _exclusive_bytes(work/'candidate.bundle', evidence['bundle'])
    for key, filename in (('dispatch_raw', 'dispatch.json'), ('stdout_raw', 'stdout.log'),
                          ('build_raw', 'build.json'), ('import_raw', 'import.json')):
        _exclusive_bytes(work/filename, evidence[key])
    persist_source_snapshot(work/'source-snapshot', dict(manifest=json.loads(evidence['manifest_raw']),
        manifest_sha256=evidence['manifest_sha256'], blobs=evidence['blobs']))
    _sync_directory(work)
    if _file(fence_path, 65536) != fence_raw:
        raise RuntimeError('Reservation changed; retain partial record for inspection')
    value = dict(schema=1, phase='pending_review', evidence=verified,
                 fence_sha256=hashlib.sha256(fence_raw).hexdigest(), bundle_file='candidate.bundle',
                 published=False, merged=False, fence_released=False, resume_available=False)
    atomic_write_json(work/'candidate.json', value)
    return work/'candidate.json'


def inspect_candidate(controller_root, registration, operation_id):
    """Recheck an archived candidate without resolving its still-present fence."""
    root = Path(controller_root)
    if (not root.is_absolute() or root.resolve() != root
            or registration.get('controller_root') != str(root)
            or not isinstance(operation_id, str) or not re.fullmatch('[0-9a-f]{32}', operation_id)):
        raise ValueError('Registered controller and exact operation required')
    for parent in root.parents:
        _directory(parent)
    for directory in (root, root/'candidate-review', root/'candidate-review'/operation_id,
                      root/'model-turn-fences'):
        _directory(directory, private=True)
    work = root/'candidate-review'/operation_id
    record = json.loads(_file(work/'candidate.json', 8*1024*1024), object_pairs_hook=_pairs)
    if (not isinstance(record, dict) or type(record.get('schema')) is not int or record['schema'] != 1
            or record.get('phase') != 'pending_review' or record.get('bundle_file') != 'candidate.bundle'
            or any(record.get(k) is not False for k in ('published', 'merged', 'fence_released', 'resume_available'))
            or not isinstance(record.get('evidence'), dict)):
        raise ValueError('Incomplete review record')
    saved = record['evidence']
    binding = saved.get('turn_binding')
    if not isinstance(binding, dict) or binding.get('operation_id') != operation_id:
        raise ValueError('Review operation mismatch')
    raw, blobs, _ = load_snapshot(work/'source-snapshot', saved.get('manifest_sha256'))
    verified = bind_turn_candidate(binding, registration, manifest_raw=raw,
        manifest_sha256=saved['manifest_sha256'], blobs=blobs,
        dispatch_raw=_file(work/'dispatch.json', 8*1024*1024), stdout_raw=_file(work/'stdout.log', 8*1024*1024),
        build_raw=_file(work/'build.json', 8*1024*1024), import_raw=_file(work/'import.json', 8*1024*1024),
        bundle=_file(work/'candidate.bundle', 16*1024*1024),
        validator_id=saved.get('validator_id'), image_id=saved.get('image_id'))
    if not same_json(saved, verified):
        raise ValueError('Saved review evidence differs from archived inputs')
    fence_raw = _file(root/'model-turn-fences'/(binding['role']+'.json'), 65536)
    if hashlib.sha256(fence_raw).hexdigest() != record.get('fence_sha256'):
        raise ValueError('Reservation changed; manual reconciliation required')
    return dict(record, archive_verified=True, runtime_state_observed=False)


def inspect_candidates(controller_root, registration):
    """Bounded local inventory. Partial or unexamined records never mean ready."""
    root = Path(controller_root)
    if not root.is_absolute() or root.resolve() != root:
        raise ValueError('Absolute unlinked controller root required')
    for parent in root.parents:
        _directory(parent)
    _directory(root, private=True)
    report = dict(schema=1, records={}, invalid_entry_count=0, unexamined_count=0,
                  runtime_state_observed=False, resume_available=False, inventory_complete=False)
    if registration.get('controller_root') != str(root) or not registration.get('migration_epoch'):
        return dict(report, status='registration_missing_or_mismatched')
    queue = root/'candidate-review'
    try:
        _directory(queue, private=True)
    except FileNotFoundError:
        return dict(report, status='absent', inventory_complete=True)
    names = []
    with os.scandir(queue) as entries:
        for index, entry in enumerate(entries):
            if index >= 256:
                return dict(report, status='inventory_limit_exceeded')
            if re.fullmatch('[0-9a-f]{32}', entry.name) and entry.is_dir(follow_symlinks=False):
                names.append(entry.name)
            else:
                report['invalid_entry_count'] += 1
    for operation in sorted(names)[:32]:
        try:
            result = inspect_candidate(root, registration, operation)
            report['records'][operation] = dict(state='pending_review', archive_verified=True,
                commit=result['evidence']['commit'], role=result['evidence']['turn_binding']['role'])
        except FileNotFoundError:
            report['records'][operation] = dict(state='incomplete', archive_verified=False)
        except (ValueError, TypeError, KeyError, OSError, RecursionError):
            report['records'][operation] = dict(state='inspection_required', archive_verified=False)
    report['unexamined_count'] = max(0, len(names)-32)
    report['inventory_complete'] = not report['unexamined_count'] and not report['invalid_entry_count']
    report['status'] = 'inspected' if report['inventory_complete'] else 'partial_inventory'
    return report
