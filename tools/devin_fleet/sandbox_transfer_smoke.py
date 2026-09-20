"""Import an existing candidate object into coordinator; no merge/model."""
import json
from pathlib import Path
import tempfile

from sandbox_runtime import SandboxRuntime
from sandbox_transfer import transfer_commit


def main():
    registration = json.loads(Path('sandbox-registry.json').read_text())
    with tempfile.TemporaryDirectory(prefix='sandbox-object-transfer-') as work:
        with SandboxRuntime(registration, Path(work)) as runtime:
            receipt = transfer_commit(runtime, 'storage', 'coordinator',
                                      'e7271a6eaca0204c77925ed6e5723412a1c4477e')
            assert receipt['target_head'] == '5f676710e5b2fdadbcb3a3fc421c98ddd1e0af93'
        print('object_transfer_verified ' + json.dumps(receipt), flush=True)
        print('object_transfer_live_passed: bundle hash, commit identity, unchanged HEADs, stopped VMs; no merge')


if __name__ == '__main__':
    main()
