"""Real-role maintenance CLI acceptance with a no-op receipt and scoped STOP."""
import json
from pathlib import Path
import subprocess
import sys
import uuid

from durable import atomic_write_json
from sandbox_runtime import SandboxRuntime
from sandbox_sync import synchronize_fast_forward


def main():
    registration = json.loads(Path('sandbox-registry.json').read_text())
    registration.update(backend='sandbox', migration_epoch=str(uuid.uuid4()))
    work = Path.cwd() / ('driver-evidence-' + uuid.uuid4().hex)
    work.mkdir(mode=0o700)
    atomic_write_json(work / 'registration.json', registration)
    print('persistent_evidence=' + str(work), flush=True)
    with SandboxRuntime(registration, work) as runtime:
        with runtime.role('storage') as repo:
            head = repo.git('rev-parse', 'HEAD').strip()
        receipt = synchronize_fast_forward(runtime, 'coordinator', 'storage',
                                           head, head, work / 'attempt')
    original = (work / 'attempt/receipt.json').read_bytes()
    command = [sys.executable, str(Path(__file__).with_name('sandbox_driver.py').resolve()),
               '--registry', str(work / 'registration.json'), '--root', str(work)]
    def invoke(*arguments):
        return subprocess.run(command + list(arguments), capture_output=True, text=True,
                              timeout=180, check=False)
    status = invoke('status')
    assert status.returncode == 0, status.stderr
    assert set(json.loads(status.stdout)['roles'].values()) == {'stopped'}
    inspect = invoke('inspect-sync', '--receipt', str(work / 'attempt/receipt.json'),
                     '--operation', receipt['operation_id'], '--evidence', str(work / 'inspection'))
    assert inspect.returncode == 0, inspect.stderr
    evidence = json.loads(inspect.stdout)
    assert evidence['outcome'] == 'verified_applied'
    assert evidence['guest_root'] == '/home/agent/workspace/storage'
    assert evidence['observed_head'] == head and evidence['replay_permitted'] is False
    assert (work / 'attempt/receipt.json').read_bytes() == original
    # This STOP belongs only to the new test root, never the legacy fleet root.
    (work / 'STOP').touch(exist_ok=False)
    refused = invoke('inspect-sync', '--receipt', str(work / 'attempt/receipt.json'),
                     '--operation', receipt['operation_id'], '--evidence', str(work / 'refused'))
    assert refused.returncode == 2 and 'STOP is present' in refused.stderr
    assert not (work / 'refused').exists() and (work / 'STOP').exists()
    final = invoke('status')
    assert final.returncode == 0, final.stderr
    status_data = json.loads(final.stdout)
    assert status_data['stop_requested'] is True
    assert set(status_data['roles'].values()) == {'stopped'}
    atomic_write_json(work / 'result.json', {'inspection': evidence, 'final_status': status_data,
                                           'scoped_stop_refused': True})
    print(json.dumps(evidence), flush=True)
    print('driver_live_passed: real role no-op inspected, new process CLI, STOP refused, all VMs stopped')


if __name__ == '__main__':
    main()
