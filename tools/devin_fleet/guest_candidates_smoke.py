"""Transfer committed pending evidence between registered VMs, no model/merge."""
import json
from pathlib import Path
import sys
import tempfile

import fleet
from sandbox_runtime import SandboxRuntime


def main():
    source = Path(sys.argv[1])
    state = json.loads((source / 'state.json').read_text(encoding='utf-8'))
    roles = json.loads((source / 'roles.json').read_text(encoding='utf-8'))
    registration = json.loads(Path('sandbox-registry.json').read_text())
    with tempfile.TemporaryDirectory(prefix='guest-candidates-') as work:
        with SandboxRuntime(registration, Path(work)) as runtime:
            patches, evidence = fleet.collect_guest_candidate_patches(runtime, state)
            print('candidate_collection_verified ' + json.dumps({
                'count': len(patches), 'bytes': sum(e['bytes'] for e in evidence.values())}), flush=True)
            with runtime.role('coordinator') as repo:
                prepared = fleet.prepare_guest_turn(source, repo, 'coordinator', roles['coordinator'],
                                                    state, candidate_patches=patches)
                for commit, item in evidence.items():
                    assert repo.sha256(prepared['relative'] + '/' + commit + '.patch') == item['sha256']
                assert '--resume' not in prepared['args']
                print('coordinator_evidence_verified ' + json.dumps({
                    'relative': prepared['relative'], 'base': prepared['base'],
                    'count': len(evidence), 'evidence': evidence}), flush=True)
        print('candidates_live_passed: owner VM collection, full coordinator transfer, unchanged HEAD, final stop')


if __name__ == '__main__':
    main()
