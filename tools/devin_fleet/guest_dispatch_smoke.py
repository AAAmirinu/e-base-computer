"""Opt-in production helper transport check; no model/project code runs."""
from pathlib import Path
import tempfile
import uuid

import fleet
from process_control import GlobalLock
from sandbox_control import SandboxController
from sandbox_repository import GuestRepository, GuestRepositoryError


def main():
    with GlobalLock(), tempfile.TemporaryDirectory(prefix='guest-dispatch-') as work:
        root = Path(work)
        controller = SandboxController('e-base-applications', root / 'STOP',
            sandbox_id='4cacfd64-5b54-4704-b636-dd101e35dd5b')
        controller.resume()
        repo = GuestRepository(controller, '/home/agent/workspace/applications', root / 'logs')
        try:
            assert fleet.sha(repo) == '5f15336ab623a4c2cf88671dfff19d14256d5ed7'
            assert fleet.changes(repo) == sorted([
                'docs/fleet/applications/baseline-v1.md', 'guest/applications/README.md',
                'guest/applications/share_normalize.epu', 'src/guest_applications.py',
                'tests/test_applications_guest.py'])
            missing = 'absent-' + uuid.uuid4().hex + '/file'
            assert fleet.fingerprints(repo, ['src/guest_applications.py', missing]) == {
                'src/guest_applications.py': 'd881517e5ce4ebe409d9fb2853fed64d62bd213178f0e13b28178e95f162e058',
                missing: None}
            try:
                repo.fingerprint('src')
            except GuestRepositoryError:
                assert controller.fenced
            else:
                raise AssertionError('Directory incorrectly accepted as missing')
            controller.resume()
            absent = GuestRepository(controller, '/home/agent/workspace/' + uuid.uuid4().hex, root / 'absent')
            try:
                absent.fingerprint('file')
            except GuestRepositoryError:
                assert controller.fenced
            else:
                raise AssertionError('Missing repository root accepted')
            print('guest_dispatch_live_passed: sha, exact changes, hash, missing file, directory and missing-root fences')
        finally:
            controller.stop()


if __name__ == '__main__':
    main()
