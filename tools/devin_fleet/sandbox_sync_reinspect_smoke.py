"""Reinspect an explicitly selected trusted interruption-probe evidence folder."""
import json
from pathlib import Path
import sys
import uuid

from sandbox_runtime import SandboxRuntime
from sandbox_sync_recovery import inspect_sync_recovery
from sandbox_sync_smoke import ProbeRuntime


def main():
    work = Path(sys.argv[1])
    if not work.is_absolute():
        raise ValueError('Explicit absolute evidence directory required')
    registration = json.loads((work / 'registration.json').read_text())
    previous = json.loads((work / 'result.json').read_text())
    raw = (work / 'attempt/receipt.json').read_bytes()
    receipt = json.loads(raw)
    driver = work / ('reinspection-' + uuid.uuid4().hex)
    driver.mkdir(mode=0o700)
    with SandboxRuntime(registration, driver) as runtime:
        probe = ProbeRuntime(runtime, previous['guest_probe_relative'])
        evidence = inspect_sync_recovery(probe, raw, receipt['operation_id'], driver / 'evidence')
        assert evidence['outcome'] == 'verified_applied'
        assert evidence['replay_permitted'] is False
        assert (work / 'attempt/receipt.json').read_bytes() == raw
        print(json.dumps(evidence), flush=True)
    print('reinspection_live_passed: exact lineage and transfer shape, unchanged original, VM stopped')


if __name__ == '__main__':
    main()
