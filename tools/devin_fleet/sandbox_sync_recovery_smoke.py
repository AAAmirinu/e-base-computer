"""Live no-op receipt reconciliation; no branch update or failure injection."""
import json
from pathlib import Path
import tempfile
import uuid

from sandbox_runtime import SandboxRuntime
from sandbox_sync import synchronize_fast_forward
from sandbox_sync_recovery import inspect_sync_recovery
from sandbox_sync_smoke import ProbeRuntime


def main():
    registration = json.loads(Path('sandbox-registry.json').read_text())
    registration.update(backend='sandbox', migration_epoch=str(uuid.uuid4()))
    with tempfile.TemporaryDirectory(prefix='sync-recovery-probe-') as temporary:
        work = Path(temporary)
        with SandboxRuntime(registration, work) as runtime:
            probe = ProbeRuntime(runtime, '.fleet/sync-probe-99afffa1e32d4139aff44bf3354496a0')
            with probe.role('storage') as repo:
                head = repo.git('rev-parse', 'HEAD').strip()
            receipt = synchronize_fast_forward(probe, 'coordinator', 'storage',
                                               head, head, work / 'attempt')
            path = work / 'attempt/receipt.json'
            original = path.read_bytes()
            evidence = inspect_sync_recovery(probe, original, receipt['operation_id'],
                                             work / 'recovery')
            assert evidence['outcome'] == 'verified_applied'
            assert evidence['replay_permitted'] is False
            assert evidence['observed_head'] == head
            assert path.read_bytes() == original
            print(json.dumps(evidence), flush=True)
        print('recovery_live_passed: no-op receipt reconciled, original unchanged, VM stopped')


if __name__ == '__main__':
    main()
