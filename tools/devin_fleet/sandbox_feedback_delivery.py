"""Maintenance-only failed-result delivery. No model calls or hold resolution."""
import hashlib
import json
import os
from pathlib import Path

from durable import atomic_write_json
from sandbox_snapshot import capture_source_snapshot, _unchanged
from validation_feedback_store import persist_feedback
from validation_failure_feedback import build_feedback
from validation_snapshot_input import _directory, _file, load_snapshot, load_capture, digest_argument
from validation_dispatch_receipt import _pairs


def deliver_feedback(repo, feedback, payload, *, require_existing=False):
    """Quiescent lease required; bytes must come from the verified outer store.

    This delivers evidence, not permission to execute a model. The whole source
    manifest is checked, including modes and unchanged tracked files.
    """
    canonical = (json.dumps(feedback, sort_keys=True, ensure_ascii=True,
                            allow_nan=False, separators=(',', ':')) + '\n').encode()
    if payload != canonical:
        raise ValueError('Stored feedback differs from rebuilt evidence')
    capture = feedback['capture_evidence']['capture']
    if repo.controller.sandbox_id != capture['sandbox_id']:
        raise ValueError('Wrong destination VM')
    snapshot = capture_source_snapshot(repo, capture['source_checkpoint'])
    if snapshot['manifest_sha256'] != capture['manifest_sha256']:
        raise ValueError('Current source differs from failed snapshot')
    digest = hashlib.sha256(payload).hexdigest()
    target = '.fleet/validation-feedback-' + digest + '.json'
    if repo.path_kind('.fleet') != 'directory':
        raise ValueError('Existing controller metadata directory required')
    kind = repo.path_kind(target)
    if kind == 'missing':
        if require_existing:
            raise ValueError('Previously delivered feedback required')
        repo.write_large_bytes(target, payload)
    elif kind != 'regular' or repo.read_bytes(target, max_bytes=8 * 1024 * 1024) != payload:
        raise ValueError('Conflicting or unsafe destination; preserve and inspect')
    if repo.read_bytes(target, max_bytes=8 * 1024 * 1024) != payload:
        raise RuntimeError('Feedback readback mismatch')
    _unchanged(repo, capture['source_checkpoint'])
    return {'schema': 1, 'role': capture['role'], 'sandbox_id': capture['sandbox_id'],
            'feedback_sha256': digest, 'guest_path': target,
            'manifest_sha256': snapshot['manifest_sha256'], 'phase': 'copied',
            'source_freshness_verified': True, 'validation_passed': False,
            'model_executed': False, 'hold_cleared': False}


def verify_turn_feedback(repo, role, payload, expected_sha256):
    """Trusted caller supplies an independently verified outer feedback digest.

    A guest file or model claim must never select this digest. This check binds
    the next turn's input; it does not authorize resolving a hold or execution.
    """
    digest_argument(expected_sha256)
    if (not isinstance(payload, bytes) or len(payload) > 8 * 1024 * 1024 or
            hashlib.sha256(payload).hexdigest() != expected_sha256):
        raise ValueError('Feedback input hash/size mismatch')
    def reject_constant(value):
        raise ValueError('Nonfinite feedback')
    value = json.loads(payload, object_pairs_hook=_pairs, parse_constant=reject_constant)
    if (not isinstance(value, dict) or type(value.get('schema')) is not int or value['schema'] != 1 or
            value.get('kind') != 'failed_validation_feedback' or
            any(value.get(k) is not False for k in ('validation_passed', 'replay_permitted', 'hold_cleared'))):
        raise ValueError('Invalid non-accepting feedback')
    capture = value.get('capture_evidence', {}).get('capture', {})
    if capture.get('role') != role or repo.guest_root != '/home/agent/workspace/' + role:
        raise ValueError('Feedback belongs to a different role')
    deliver_feedback(repo, value, payload, require_existing=True)
    return expected_sha256


def main():
    import argparse
    import re
    from sandbox_runtime import SandboxRuntime
    from validation_snapshot_dispatch import inventory, UUID
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dispatch', required=True)
    parser.add_argument('--snapshot', required=True)
    parser.add_argument('--manifest-sha256', required=True, type=digest_argument)
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
    registration = json.loads(_file(root / 'sandbox-registry.json', 1024 * 1024), object_pairs_hook=_pairs)
    with SandboxRuntime(registration, dispatch) as runtime:
        values, vm = inventory()
        if any(v['status'] != 'stopped' for v in values):
            raise RuntimeError('All VMs must be stopped')
        _, _, manifest = load_snapshot(source, args.manifest_sha256)
        capture = load_capture(source.parent / 'capture.json', source, args.manifest_sha256,
                               manifest, registration['roles'])
        feedback = build_feedback(_file(dispatch / 'dispatch.json', 8 * 1024 * 1024),
            _file(dispatch / 'stdout.log', 8 * 1024 * 1024), capture_evidence=capture,
            expected_vm=UUID, live_vm=vm)
        stored = persist_feedback(dispatch, feedback)
        payload = _file(Path(stored['path']), 8 * 1024 * 1024)
        delivery_path = dispatch / 'feedback-delivery.json'
        # Refuse to overwrite an interrupted delivery. Explicit recovery is needed.
        if os.path.lexists(delivery_path):
            raise RuntimeError('Existing delivery transaction requires inspection')
        atomic_write_json(delivery_path, {'schema': 1, 'phase': 'prepared',
            'feedback_sha256': stored['sha256'], 'role': capture['capture']['role'],
            'model_executed': False, 'hold_cleared': False})
        print('delivery_prepared: checking full source manifest', flush=True)
        with runtime.role(capture['capture']['role']) as repo:
            result = deliver_feedback(repo, feedback, payload)
        values, _ = inventory()
        if any(v['status'] != 'stopped' for v in values):
            raise RuntimeError('Post-delivery VM stop check failed')
        result.update(phase='delivered', source_vm_stopped=True)
        atomic_write_json(delivery_path, result)
        print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
