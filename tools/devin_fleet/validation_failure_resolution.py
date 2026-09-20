"""Explicit rejection of a completed failed validation, never test acceptance."""
import hashlib
import json
import re

from validation_dispatch_receipt import _pairs
from validation_failure_feedback import build_feedback


def _decode(raw):
    if not isinstance(raw, bytes) or len(raw) > 8 * 1024 * 1024:
        raise ValueError('Invalid evidence size')
    def reject(value):
        raise ValueError('Nonfinite evidence')
    value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=reject)
    if not isinstance(value, dict):
        raise ValueError('Evidence object required')
    return value


def canonical(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False,
                       separators=(',', ':')) + '\n').encode()


def build_resolution(raw, output, feedback_raw, delivery_raw, *, dispatch_id, capture_evidence, expected_vm, live_vm):
    if not isinstance(dispatch_id, str) or not re.fullmatch('[0-9a-f]{32}', dispatch_id):
        raise ValueError('Explicit outer dispatch identity required')
    feedback = build_feedback(raw, output, capture_evidence=capture_evidence,
                              expected_vm=expected_vm, live_vm=live_vm)
    if feedback_raw != canonical(feedback):
        raise ValueError('Stored feedback differs from verified evidence')
    delivery = _decode(delivery_raw)
    capture = capture_evidence['capture']
    digest = hashlib.sha256(feedback_raw).hexdigest()
    if (type(delivery.get('schema')) is not int or delivery['schema'] != 1 or
            delivery.get('phase') != 'delivered' or
            delivery.get('role') != capture['role'] or
            delivery.get('sandbox_id') != capture['sandbox_id'] or
            delivery.get('manifest_sha256') != capture['manifest_sha256'] or
            delivery.get('feedback_sha256') != digest or
            delivery.get('guest_path') != '.fleet/validation-feedback-' + digest + '.json' or
            delivery.get('source_vm_stopped') is not True or
            delivery.get('source_freshness_verified') is not True or
            any(delivery.get(k) is not False for k in ('validation_passed', 'model_executed', 'hold_cleared'))):
        raise ValueError('Complete bound delivery required')
    return {'schema': 1, 'outcome': 'rejected_awaiting_repair',
        'dispatch_id': dispatch_id,
        'dispatch_sha256': hashlib.sha256(raw).hexdigest(),
        'stdout_sha256': hashlib.sha256(output).hexdigest(),
        'feedback_sha256': digest, 'delivery_sha256': hashlib.sha256(delivery_raw).hexdigest(),
        'operation': feedback['operation'], 'manifest_sha256': capture['manifest_sha256'],
        'role': capture['role'], 'sandbox_id': expected_vm,
        'validation_passed': False, 'replay_permitted': False,
        'candidate_accepted': False, 'model_start_authorized': False}


def verify_resolution(raw, output, feedback_raw, delivery_raw, resolution_raw, dispatch_id, expected_vm, live_vm):
    journal = _decode(raw)
    expected = build_resolution(raw, output, feedback_raw, delivery_raw,
        dispatch_id=dispatch_id, capture_evidence=journal.get('capture_evidence'), expected_vm=expected_vm, live_vm=live_vm)
    if resolution_raw != canonical(expected):
        raise ValueError('Resolution changed or is not bound to original rejection')
    return expected


def main():
    import argparse
    import fcntl
    import os
    from pathlib import Path
    import re
    from validation_snapshot_input import _directory, _file, load_snapshot, load_capture, digest_argument
    from validation_snapshot_dispatch import inventory, UUID
    from validation_feedback_store import persist_feedback
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dispatch', required=True)
    parser.add_argument('--snapshot', required=True)
    parser.add_argument('--manifest-sha256', type=digest_argument, required=True)
    args = parser.parse_args()
    if os.environ.get('WSL_DISTRO_NAME') != 'EBase-Sandboxes' or os.getuid() != 1000:
        raise RuntimeError('Dedicated distro required')
    root = Path('/home/fleet/controller-validation')
    dispatch, source = Path(args.dispatch), Path(args.snapshot)
    if dispatch.parent != root or not re.fullmatch('dispatch-[0-9a-f]{32}', dispatch.name):
        raise ValueError('Dedicated dispatch required')
    for path in (dispatch, source):
        _directory(path)
        if root not in path.parents:
            raise ValueError('Dedicated input required')
        for parent in path.parents:
            meta = parent.stat()
            if meta.st_uid not in (0, os.getuid()) or meta.st_mode & 0o022:
                raise ValueError('Unprotected ancestor')
    with open('/tmp/e-base-devin-fleet-global.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        values, vm = inventory()
        if any(v['status'] != 'stopped' for v in values):
            raise RuntimeError('All VMs must be stopped')
        _, _, manifest = load_snapshot(source, args.manifest_sha256)
        roles = _decode(_file(root/'sandbox-registry.json', 1024*1024))['roles']
        capture = load_capture(source.parent/'capture.json', source, args.manifest_sha256, manifest, roles)
        def read(name):
            return _file(dispatch/name, 8*1024*1024)
        if os.path.lexists(dispatch/'closure.json'):
            raise ValueError('Synthetic closure conflicts with actual-source resolution')
        resolution = build_resolution(read('dispatch.json'), read('stdout.log'),
            read('failure-feedback.json'), read('feedback-delivery.json'),
            dispatch_id=dispatch.name.removeprefix('dispatch-'), capture_evidence=capture, expected_vm=UUID, live_vm=vm)
        stored = persist_feedback(dispatch, resolution, filename='failure-resolution.json')
        print(json.dumps({'path': stored['path'], 'sha256': stored['sha256'],
            'created': stored['created'], 'outcome': resolution['outcome'],
            'validation_passed': False, 'replay_permitted': False}), flush=True)


if __name__ == '__main__':
    main()
