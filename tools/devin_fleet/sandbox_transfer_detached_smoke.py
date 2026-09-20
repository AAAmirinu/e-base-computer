"""Transfer a synthetic unreferenced commit without changing working branches."""
import json
from pathlib import Path
import tempfile
import uuid

from sandbox_runtime import SandboxRuntime
from sandbox_transfer import transfer_commit


def main():
    registration = json.loads(Path('sandbox-registry.json').read_text())
    with tempfile.TemporaryDirectory(prefix='sandbox-detached-transfer-') as work:
        with SandboxRuntime(registration, Path(work)) as runtime:
            with runtime.role('storage') as source:
                before = source.git('rev-parse', 'HEAD').strip()
                tree = source.git('rev-parse', 'HEAD^{tree}').strip()
                commit = source.git('-c', 'user.name=Transfer Probe', '-c',
                                    'user.email=transfer-probe@invalid.example',
                                    'commit-tree', tree, '-p', before, '-m',
                                    'Isolated transfer probe ' + uuid.uuid4().hex).strip()
                assert not source.git('for-each-ref', '--contains=' + commit).strip()
                assert source.git('rev-parse', 'HEAD').strip() == before
            receipt = transfer_commit(runtime, 'storage', 'coordinator', commit)
            assert receipt['source_head'] == before
            with runtime.role('storage') as source:
                assert source.git('rev-parse', receipt['bundle_ref']).strip() == commit
            print(json.dumps({'unreferenced_before_export': True,
                              'recovery_ref_retained': True, **receipt}), flush=True)
        print('detached_transfer_live_passed: unreferenced commit imported, HEADs unchanged, VMs stopped')


if __name__ == '__main__':
    main()
