"""Controlled SIGKILL of this trusted guest helper; outer owner always stops VM.

No project source, model or physical-PC reboot. Never a production entrypoint.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import uuid


def guest(operation):
    from sandbox_validation_container import admit_image, create_arguments, verify_created_container
    from validation_container_smoke import IMAGE, run
    if re.fullmatch('[0-9a-f]{32}', operation) is None:
        raise ValueError('Invalid operation')
    admit_image(json.loads(run(['docker', 'image', 'inspect', IMAGE]))[0])
    container = run(create_arguments(IMAGE, operation)).strip()
    verify_created_container(json.loads(run(['docker', 'inspect', container]))[0], IMAGE, operation)
    run(['docker', 'start', container])
    state = json.loads(run(['docker', 'inspect', '--format', '{{json .State}}', container]))
    if state['Running'] is not True:
        raise RuntimeError('Probe container did not start')
    print(json.dumps({'operation': operation, 'container_id': container,
                      'guest_pid': os.getpid(), 'running_before_crash': True}), flush=True)
    # Deliberately bypass Python finally handlers, only for this owned helper.
    os.kill(os.getpid(), signal.SIGKILL)


def main():
    import fcntl
    from durable import atomic_write_json, _sync_directory
    from validation_dispatch_recovery import inspect_record
    from validation_snapshot_dispatch import inventory, SBX, UUID, DIGEST, IMAGE
    if os.environ.get('WSL_DISTRO_NAME') != 'EBase-Sandboxes' or os.getuid() != 1000:
        raise RuntimeError('Dedicated fleet controller required')
    with open('/tmp/e-base-devin-fleet-global.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        values, _ = inventory()
        if any(value['status'] != 'stopped' for value in values):
            raise RuntimeError('All VMs must be stopped')
        policy = subprocess.run(SBX + ['policy', 'check', 'network', '--sandbox', 'e-base-validation',
            '--json', 'registry-1.docker.io'], capture_output=True, text=True, timeout=30)
        if json.loads(policy.stdout)['allowed'] is not False:
            raise RuntimeError('Network denial required')
        operation = uuid.uuid4().hex
        directory = Path('/home/fleet/controller-validation/dispatch-' + operation)
        directory.mkdir(mode=0o700)
        _sync_directory(directory.parent)
        journal = {'schema': 1, 'phase': 'running', 'sandbox_id': UUID, 'manifest_sha256': DIGEST,
            'image_id': IMAGE, 'base': 'e7271a6eaca0204c77925ed6e5723412a1c4477e',
            'validation_passed': False, 'probe_kind': 'trusted_driver_sigkill', 'source_executed': False}
        atomic_write_json(directory / 'dispatch.json', journal)
        original = (directory / 'dispatch.json').read_bytes()
        evidence = {'operation': operation, 'journal_sha256': hashlib.sha256(original).hexdigest(),
                    'physical_reboot_tested': False, 'source_executed': False}
        def call(*args, check=True):
            return subprocess.run(SBX + list(args), capture_output=True, text=True, timeout=45, check=check)
        try:
            crash = call('exec', 'e-base-validation', 'python3', '/tmp/validation_crash_probe.py', '--guest', operation, check=False)
            evidence['guest_returncode'] = crash.returncode
            lines = [json.loads(line) for line in crash.stdout.splitlines() if line.startswith('{')]
            if crash.returncode not in (137, -signal.SIGKILL) or len(lines) != 1 or lines[0].get('operation') != operation:
                raise RuntimeError('Expected owned-helper crash not observed')
            container = lines[0]['container_id']
            if not re.fullmatch('[0-9a-f]{64}', container):
                raise RuntimeError('Invalid owned container identity')
            evidence['container_id'] = container
            before = json.loads(call('exec', 'e-base-validation', 'docker', 'inspect', container).stdout)[0]
            if before['State']['Running'] is not True or before['Config']['Labels'].get('e-base.validation.operation') != operation:
                raise RuntimeError('Orphan probe not bound to this operation')
            evidence['container_survived_driver_crash'] = True
            call('stop', 'e-base-validation')
            _, stopped = inventory()
            if stopped['status'] != 'stopped':
                raise RuntimeError('First VM stop unverified')
            # A read-only inspect starts the dedicated VM; never start container.
            after = json.loads(call('exec', 'e-base-validation', 'docker', 'inspect', container).stdout)[0]
            evidence['container_running_after_vm_restart'] = after['State']['Running']
            evidence['restart_policy'] = after['HostConfig']['RestartPolicy']['Name']
            if after['State']['Running'] is not False or evidence['restart_policy'] != 'no':
                raise RuntimeError('Unexpected container auto-restart')
        finally:
            call('stop', 'e-base-validation')
            _, stopped = inventory()
            evidence['vm_stopped'] = stopped['status'] == 'stopped'
            evidence['journal_unchanged'] = (directory / 'dispatch.json').read_bytes() == original
            evidence['recovery'] = inspect_record(original, None, digest=DIGEST, image=IMAGE,
                base=journal['base'], expected_vm=UUID, live_vm=stopped)
            atomic_write_json(directory / 'crash-evidence.json', evidence)
            print(json.dumps({'directory': str(directory), 'evidence': evidence}), flush=True)
        if (not evidence['vm_stopped'] or not evidence['journal_unchanged'] or
                evidence['recovery']['reason'] != 'incomplete_dispatch_phase'):
            raise RuntimeError('Crash containment evidence incomplete')


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--guest':
        guest(sys.argv[2])
    else:
        main()
