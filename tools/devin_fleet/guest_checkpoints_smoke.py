"""Read synthetic checkpoints through the production helper; no model work."""
import json
from pathlib import Path
import tempfile
import uuid

import fleet
from sandbox_runtime import SandboxRuntime


def main():
    registry = json.loads(Path('sandbox-registry.json').read_text())
    with tempfile.TemporaryDirectory(prefix='guest-checkpoint-') as work:
        with SandboxRuntime(registry, Path(work)) as runtime:
            with runtime.role('machine') as repo:
                directory = '.fleet/checkpoint-probe-' + uuid.uuid4().hex
                repo.make_directory(directory)
                relative = directory + '/report.json'
                repo.write_bytes(relative, b'{"summary":"synthetic transport only"}\n')
                assert fleet.read_repository_json(repo, relative)['summary'] == 'synthetic transport only'
                repo.write_bytes(relative, b'{"summary":"one","summary":"two"}')
                try:
                    fleet.read_repository_json(repo, relative)
                except ValueError:
                    assert repo.controller.fenced
                else:
                    raise AssertionError('Ambiguous checkpoint accepted')
        print('checkpoint_live_passed: guest object retrieval, duplicate rejection, final VM stop')


if __name__ == '__main__':
    main()
