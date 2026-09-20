"""Synthetic guest ownership metadata checks; no model/project execution."""
import json
from pathlib import Path
import tempfile
import uuid

import fleet
from sandbox_runtime import SandboxRuntime


def main():
    registration = json.loads(Path('sandbox-registry.json').read_text())
    directory = '.fleet/ownership-probe-' + uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix='guest-ownership-') as work:
        root = Path(work)
        with SandboxRuntime(registration, root) as runtime:
            with runtime.role('machine') as repo:
                repo.make_directory(directory)
                repo.write_bytes(directory + '/regular', b'probe')
                fleet.check_owned_changes(repo, [directory + '/regular', directory + '/absent/file'], [], 'machine')
                setup = "import os,sys; p=sys.argv[1]; open(p+'/hard','wb').close(); os.link(p+'/hard',p+'/hard2'); os.symlink('/etc/os-release',p+'/link'); os.symlink('/etc',p+'/parent'); os.mkfifo(p+'/pipe')"
                result = repo.controller.execute(['python3', '-I', '-c', setup, directory],
                    cwd=repo.guest_root, log_path=root / 'fixtures.log', timeout=30,
                    external_stop=runtime.stop_path)
                assert result.returncode == 0
            for target in ('link', 'hard', 'pipe', 'parent/absent'):
                with runtime.role('machine') as repo:
                    try:
                        fleet.check_owned_changes(repo, [directory + '/' + target], [], 'machine')
                    except RuntimeError:
                        assert repo.controller.fenced
                    else:
                        raise AssertionError('Unsafe path admitted: ' + target)
        print('ownership_live_passed: regular/deletion accepted; symlink/hardlink/FIFO/linked-parent rejected; VM stopped')


if __name__ == '__main__':
    main()
