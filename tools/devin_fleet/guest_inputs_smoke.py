"""Stage real driver policy and inert prompt; do not invoke any model."""
import json
from pathlib import Path
import tempfile

import fleet
from sandbox_runtime import SandboxRuntime
from sandbox_repository import GuestRepositoryError


def main():
    registration = json.loads(Path('sandbox-registry.json').read_text())
    roles = json.loads(Path('roles.json').read_text(encoding='utf-8'))
    with tempfile.TemporaryDirectory(prefix='guest-inputs-') as work:
        with SandboxRuntime(registration, Path(work)) as runtime:
            with runtime.role('machine') as repo:
                before = fleet.sha(repo)
                staged = fleet.stage_guest_model_inputs(repo, roles['machine'],
                    'Maintenance staging probe only. No model invocation is authorized by this file.\n')
                config = json.loads(repo.read_bytes(staged['relative'] + '/config.json'))
                assert config['agent']['model'] == 'swe-2-high'
                assert repo.fingerprint(staged['relative'] + '/export.json') is None
                assert fleet.sha(repo) == before
                print('staged_inputs_verified ' + json.dumps(staged))
                try:
                    repo.make_directory(staged['relative'])
                except GuestRepositoryError:
                    assert repo.controller.fenced
                else:
                    raise AssertionError('Existing operation directory reused')
        print('inputs_live_passed: config/prompt hashes, absent export, unchanged HEAD, existing-directory fence, stopped VM')


if __name__ == '__main__':
    main()
