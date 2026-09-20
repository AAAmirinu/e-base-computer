"""Capture an explicit role's actual source as inert blobs; no model execution."""
import argparse
import json
from pathlib import Path
import uuid

import fleet
from sandbox_runtime import SandboxRuntime
from sandbox_snapshot import capture_source_snapshot, persist_source_snapshot
from durable import atomic_write_json


def main():
    registration = json.loads(Path('sandbox-registry.json').read_text())
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--role', choices=sorted(registration['roles']), required=True)
    role = parser.parse_args().role
    work = Path.cwd() / ('snapshot-evidence-' + uuid.uuid4().hex)
    work.mkdir(mode=0o700)
    print('persistent_evidence=' + str(work), flush=True)
    with SandboxRuntime(registration, work) as runtime:
        with runtime.role(role) as repo:
            changed = fleet.changes(repo)
            expected = {'base': fleet.sha(repo), 'changed': changed,
                        'fingerprints': fleet.fingerprints(repo, changed)}
            snapshot = capture_source_snapshot(repo, expected)
            assert snapshot['manifest']['files']
        persist_source_snapshot(work / 'source-snapshot', snapshot)
    result = {'schema': 1, 'role': role, 'sandbox_id': registration['roles'][role]['id'],
              'base': expected['base'], 'manifest_sha256': snapshot['manifest_sha256'],
              'source_checkpoint': expected, 'snapshot_directory': str(work / 'source-snapshot'),
              'source_executed': False, 'source_vm_stopped': True,
              'file_count': len(snapshot['manifest']['files']),
              'source_bytes': sum(f['size'] for f in snapshot['manifest']['files']),
              'blob_count': len(snapshot['blobs'])}
    atomic_write_json(work / 'capture.json', result)
    print(json.dumps(result), flush=True)
    print('source_snapshot_live_passed: actual source and modes captured, HEAD preserved, inert persistence, VM stopped')


if __name__ == '__main__':
    main()
