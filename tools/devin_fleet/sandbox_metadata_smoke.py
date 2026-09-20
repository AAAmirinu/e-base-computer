"""Restore local metadata exclusion on staged clones, preserving source changes."""
import json
from pathlib import Path
import tempfile

import fleet
from sandbox_metadata import configure_guest_metadata
from sandbox_runtime import SandboxRuntime


def main():
    registration = json.loads(Path('sandbox-registry.json').read_text())
    results = {}
    with tempfile.TemporaryDirectory(prefix='sandbox-metadata-') as temporary:
        with SandboxRuntime(registration, Path(temporary)) as runtime:
            for role in registration['roles']:
                with runtime.role(role) as repo:
                    before = [p for p in fleet.changes(repo) if p != '.fleet' and not p.startswith('.fleet/')]
                    fingerprints = fleet.fingerprints(repo, before)
                    head = repo.git('rev-parse', 'HEAD').strip()
                    result = configure_guest_metadata(repo)
                    after = fleet.changes(repo)
                    assert sorted(after) == sorted(before), (role, before, after)
                    assert fleet.fingerprints(repo, after) == fingerprints
                    assert repo.git('rev-parse', 'HEAD').strip() == head
                    assert configure_guest_metadata(repo)['changed'] is False
                    results[role] = {**result, 'head': head, 'source_changes': len(after)}
                print('metadata_verified ' + role + ' ' + json.dumps(results[role]), flush=True)
        print('metadata_live_passed: source changes and HEADs preserved, all VMs stopped', flush=True)
    print(json.dumps(results), flush=True)


if __name__ == '__main__':
    main()
