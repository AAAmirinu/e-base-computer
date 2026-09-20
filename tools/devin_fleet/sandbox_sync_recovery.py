"""Inspect interrupted synchronization without replay, reset, or original edits.

The trusted driver supplies exact receipt bytes and operation identity, not a
model-selected path. Output is fresh evidence, not authority to resume a fleet.
"""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

from durable import atomic_write_json, _sync_directory
from sandbox_sync import _check_clean, _migration_epoch


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate receipt field')
        result[key] = value
    return result


def _hash(value, length):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{' + str(length) + '}', value) is not None


def _receipt(raw, registration, expected_operation):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= 65536:
        raise ValueError('Bounded receipt bytes required')
    if not _hash(expected_operation, 32):
        raise ValueError('Exact synchronization operation required')
    def reject_constant(value):
        raise ValueError('Floating-point or nonfinite receipt value')
    value = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique,
                       parse_constant=reject_constant, parse_float=reject_constant)
    required = {'schema', 'migration_epoch', 'operation_id', 'phase', 'source_role',
                'target_role', 'source_id', 'target_id', 'before', 'baseline',
                'head_ref', 'guest_root'}
    if (not isinstance(value, dict) or not required <= value.keys() or
            value.keys() - required - {'transfer', 'no_op'} or
            type(value['schema']) is not int or value['schema'] != 2 or
            value['operation_id'] != expected_operation or
            value['migration_epoch'] != _migration_epoch(registration)):
        raise ValueError('Unbound or unsupported synchronization receipt')
    roles = registration['roles']
    source, target = value['source_role'], value['target_role']
    if (not isinstance(source, str) or not isinstance(target, str) or
            source not in roles or target not in roles or source == target or
            value['source_id'] != roles[source]['id'] or value['target_id'] != roles[target]['id']):
        raise ValueError('Synchronization VM identity mismatch')
    if any(not _hash(value[k], 40) for k in ('before', 'baseline')):
        raise ValueError('Exact commit identities required')
    root, ref = value['guest_root'], value['head_ref']
    if (not isinstance(root, str) or not root.startswith('/') or root == '/' or
            '\x00' in root or '\\' in root or '..' in root.split('/') or
            str(PurePosixPath(root)) != root or
            not isinstance(ref, str) or (ref != 'HEAD' and not ref.startswith('refs/heads/'))):
        raise ValueError('Invalid guest repository binding')
    phase = value['phase']
    if phase not in ('prepared', 'transferred', 'applying', 'complete'):
        raise ValueError('Unknown synchronization phase')
    if 'no_op' in value:
        if (value['no_op'] is not True or phase != 'complete' or
                value['before'] != value['baseline'] or 'transfer' in value):
            raise ValueError('Invalid no-op receipt')
    elif phase != 'prepared':
        transfer = value.get('transfer')
        bindings = {'source_role': source, 'target_role': target,
                    'source_id': value['source_id'], 'target_id': value['target_id'],
                    'commit': value['baseline'], 'target_head': value['before']}
        fields = set(bindings) | {'operation_id', 'source_head', 'bundle_sha256',
                                  'bundle_bytes', 'relative', 'bundle_ref'}
        if (not isinstance(transfer, dict) or
                set(transfer) != fields or
                any(transfer.get(k) != v for k, v in bindings.items()) or
                not _hash(transfer.get('operation_id'), 32) or
                not _hash(transfer.get('source_head'), 40) or
                not _hash(transfer.get('bundle_sha256'), 64) or
                type(transfer.get('bundle_bytes')) is not int or
                not 1 <= transfer['bundle_bytes'] <= 16 * 1024 * 1024 or
                transfer.get('relative') != '.fleet/object-transfer-' + transfer['operation_id'] + '/objects.bundle' or
                transfer.get('bundle_ref') != 'refs/fleet-transfers/' + transfer['operation_id']):
            raise ValueError('Transfer receipt binding mismatch')
    elif 'transfer' in value:
        raise ValueError('Unexpected prepared transfer')
    return value


def inspect_sync_recovery(runtime, raw_receipt, expected_operation, evidence_directory):
    receipt = _receipt(raw_receipt, runtime.registration, expected_operation)
    directory = Path(evidence_directory)
    if not directory.is_absolute():
        raise ValueError('Absolute private evidence directory required')
    directory.mkdir(mode=0o700)
    _sync_directory(directory.parent)
    evidence = {'schema': 1, 'phase': 'checking', 'operation_id': expected_operation,
                'migration_epoch': receipt['migration_epoch'],
                'original_sha256': hashlib.sha256(raw_receipt).hexdigest()}
    path = directory / 'inspection.json'
    atomic_write_json(path, evidence)
    with runtime.role(receipt['target_role']) as repo:
        if repo.guest_root != receipt['guest_root']:
            raise RuntimeError('Recovery repository path changed')
        head = repo.git('rev-parse', 'HEAD').strip()
        if head not in (receipt['before'], receipt['baseline']):
            raise RuntimeError('Recovery HEAD diverged')
        if _check_clean(repo, head) != receipt['head_ref']:
            raise RuntimeError('Recovery HEAD attachment changed')
        if head == receipt['baseline'] and receipt['phase'] in ('applying', 'complete'):
            if not receipt.get('no_op'):
                for commit in (receipt['before'], receipt['baseline']):
                    if repo.git('rev-parse', '--verify', commit + '^{commit}').strip() != commit:
                        raise RuntimeError('Recovery commit identity mismatch')
                if repo.git('merge-base', receipt['before'], receipt['baseline']).strip() != receipt['before']:
                    raise RuntimeError('Recovery history is not a fast-forward')
            outcome = 'verified_applied'
        elif head == receipt['before'] and receipt['phase'] in ('prepared', 'transferred'):
            outcome = 'pre_application'
        else:
            outcome = 'inspection_required'
    # Never accept a clean observation while a VM or its children remain alive.
    evidence.update(phase='inspected', outcome=outcome, observed_head=head,
                    target_id=receipt['target_id'], guest_root=receipt['guest_root'],
                    head_ref=receipt['head_ref'], replay_permitted=False)
    atomic_write_json(path, evidence)
    return evidence
