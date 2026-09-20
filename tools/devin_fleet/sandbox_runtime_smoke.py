"""Opt-in runtime ownership check, no model or generated project execution."""
import json
from pathlib import Path
import tempfile

import fleet
from sandbox_control import SandboxFenced
from sandbox_runtime import SandboxRuntime


def main():
    registration = json.loads(Path('sandbox-registry.json').read_text())
    with tempfile.TemporaryDirectory(prefix='sandbox-runtime-') as work:
        with SandboxRuntime(registration, Path(work)) as runtime:
            with runtime.role('machine') as old:
                assert fleet.sha(old) == '472781a6c824ec8201d8e23ab06a1e08322be045'
            with runtime.role('machine') as current:
                try:
                    old.git('rev-parse', 'HEAD')
                except SandboxFenced:
                    pass
                else:
                    raise AssertionError('Old lease admitted')
                old.controller.stop()
                assert not current.controller.fenced
                assert fleet.sha(current) == '472781a6c824ec8201d8e23ab06a1e08322be045'
            with runtime.role('applications') as repo:
                assert fleet.sha(repo) == '5f15336ab623a4c2cf88671dfff19d14256d5ed7'
                assert len(fleet.changes(repo)) == 5
        print('runtime_live_passed: registered role routing, sequential leases, stale handle rejection, final VM stop')


if __name__ == '__main__':
    main()
