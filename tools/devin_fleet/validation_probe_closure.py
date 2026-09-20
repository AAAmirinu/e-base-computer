"""Explicit closure of an owned synthetic crash probe, never test acceptance."""
import hashlib
import json
import re
from validation_dispatch_receipt import _pairs


def evidence(raw, crash_raw, operation, expected_vm):
    journal = json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs)
    crash = json.loads(crash_raw.decode('utf-8'), object_pairs_hook=_pairs)
    if not isinstance(journal, dict) or not isinstance(crash, dict):
        raise ValueError('Invalid probe evidence')
    if (type(journal.get('schema')) is not int or journal['schema'] != 1 or journal.get('phase') != 'running' or
            journal.get('probe_kind') != 'trusted_driver_sigkill' or journal.get('source_executed') is not False or
            journal.get('validation_passed') is not False or journal.get('sandbox_id') != expected_vm):
        raise ValueError('Only unexecuted synthetic crash probes can be closed here')
    if not isinstance(operation, str) or re.fullmatch('[0-9a-f]{32}', operation) is None:
        raise ValueError('Invalid operation')
    if not isinstance(journal.get('image_id'), str) or re.fullmatch('sha256:[0-9a-f]{64}', journal['image_id']) is None:
        raise ValueError('Invalid image identity')
    container = crash.get('container_id')
    if not isinstance(container, str) or re.fullmatch('[0-9a-f]{64}', container) is None:
        raise ValueError('Invalid container identity')
    if (crash.get('operation') != operation or crash.get('journal_sha256') != hashlib.sha256(raw).hexdigest() or
            crash.get('source_executed') is not False or type(crash.get('guest_returncode')) is not int or
            crash['guest_returncode'] not in (137, -9) or
            crash.get('container_survived_driver_crash') is not True or
            crash.get('container_running_after_vm_restart') is not False or crash.get('restart_policy') != 'no' or
            crash.get('vm_stopped') is not True or crash.get('journal_unchanged') is not True):
        raise ValueError('Crash containment not established')
    return journal, crash


def verify_closure(raw, crash_raw, closure_raw, operation, expected_vm, live_vm):
    journal, crash = evidence(raw, crash_raw, operation, expected_vm)
    closure = json.loads(closure_raw.decode('utf-8'), object_pairs_hook=_pairs)
    expected = {'schema': 1, 'action': 'abandon_synthetic_probe_no_replay', 'operation': operation,
        'sandbox_id': expected_vm, 'journal_sha256': hashlib.sha256(raw).hexdigest(),
        'crash_sha256': hashlib.sha256(crash_raw).hexdigest(), 'container_id': crash['container_id'],
        'image_id': journal['image_id'], 'container_stopped': True, 'vm_stopped': True,
        'validation_passed': False, 'replay_permitted': False}
    if (not isinstance(closure, dict) or closure != expected or
            any(type(closure[k]) is not type(v) for k, v in expected.items()) or
            not isinstance(live_vm, dict) or live_vm.get('id') != expected_vm or live_vm.get('status') != 'stopped'):
        raise ValueError('Closure binding or current VM state mismatch')
    return expected


def main():
    import argparse
    import fcntl
    import os
    from pathlib import Path
    import subprocess
    from durable import _sync_directory
    from validation_pending_gate import _read
    from validation_snapshot_dispatch import inventory, SBX, UUID
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory')
    parser.add_argument('--journal-sha256', required=True)
    args = parser.parse_args()
    if os.environ.get('WSL_DISTRO_NAME') != 'EBase-Sandboxes' or os.getuid() != 1000:
        raise RuntimeError('Dedicated controller required')
    path = Path(args.directory)
    if (path.parent != Path('/home/fleet/controller-validation') or path.resolve() != path or
            re.fullmatch('dispatch-[0-9a-f]{32}', path.name) is None):
        raise ValueError('Exact dispatch directory required')
    meta = path.stat()
    if meta.st_uid != os.getuid() or meta.st_mode & 0o077:
        raise ValueError('Private caller-owned directory required')
    with open('/tmp/e-base-devin-fleet-global.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        raw, crash_raw = _read(path / 'dispatch.json'), _read(path / 'crash-evidence.json')
        if hashlib.sha256(raw).hexdigest() != args.journal_sha256:
            raise ValueError('Operator-selected journal hash mismatch')
        operation = path.name.removeprefix('dispatch-')
        journal, crash = evidence(raw, crash_raw, operation, UUID)
        if (path / 'closure.json').exists():
            raise ValueError('Closure already exists; no overwrite')
        values, _ = inventory()
        if any(v['status'] != 'stopped' for v in values):
            raise RuntimeError('All VMs must be stopped before inspection')
        try:
            query = subprocess.run(SBX + ['exec', 'e-base-validation', 'docker', 'inspect', crash['container_id']],
                capture_output=True, text=True, check=True, timeout=30)
            observed = json.loads(query.stdout)[0]
            if (observed['Id'] != crash['container_id'] or observed['Image'] != journal['image_id'] or
                    observed['Config']['Labels'].get('e-base.validation.operation') != operation or
                    observed['State']['Running'] is not False or observed['HostConfig']['RestartPolicy']['Name'] != 'no'):
                raise ValueError('Fresh owned-container stop evidence mismatch')
        finally:
            subprocess.run(SBX + ['stop', 'e-base-validation'], check=True, timeout=30)
        _, vm = inventory()
        if vm['status'] != 'stopped' or _read(path / 'dispatch.json') != raw or _read(path / 'crash-evidence.json') != crash_raw:
            raise ValueError('Stop or preserved evidence check failed')
        closure = {'schema': 1, 'action': 'abandon_synthetic_probe_no_replay', 'operation': operation,
            'sandbox_id': UUID, 'journal_sha256': hashlib.sha256(raw).hexdigest(),
            'crash_sha256': hashlib.sha256(crash_raw).hexdigest(), 'container_id': crash['container_id'],
            'image_id': journal['image_id'], 'container_stopped': True, 'vm_stopped': True,
            'validation_passed': False, 'replay_permitted': False}
        payload = json.dumps(closure, sort_keys=True).encode()
        verify_closure(raw, crash_raw, payload, operation, UUID, vm)
        fd = os.open(path / 'closure.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        _sync_directory(path)
        print(json.dumps({'closure': str(path / 'closure.json'), **closure}), flush=True)


if __name__ == '__main__':
    main()
