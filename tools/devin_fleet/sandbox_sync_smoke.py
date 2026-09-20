"""Live sync on disposable guest repositories, never staged working branches."""
from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
import uuid

from sandbox_repository import GuestRepository
from sandbox_repository import GuestRepositoryError
from sandbox_runtime import SandboxRuntime
from sandbox_sync import synchronize_fast_forward
from sandbox_transfer import transfer_commit


class ProbeRuntime:
    def __init__(self, runtime, relative):
        self.runtime, self.relative = runtime, relative
        self.registration = runtime.registration

    @contextmanager
    def role(self, role):
        with self.runtime.role(role) as outer:
            yield GuestRepository(outer.controller, outer.guest_root + '/' + self.relative,
                                  outer.log_dir, external_stop=outer.external_stop)


def commit(repo, message):
    repo.git('-c', 'user.name=Sync Probe', '-c', 'user.email=sync@invalid.example',
             '-c', 'core.hooksPath=/dev/null', 'commit', '--allow-empty', '-m', message)
    return repo.git('rev-parse', 'HEAD').strip()


def main():
    registration = json.loads(Path('sandbox-registry.json').read_text())
    # This epoch identifies only this isolated probe, not a production migration.
    registration.update(backend='sandbox', migration_epoch=str(uuid.uuid4()))
    relative = '.fleet/sync-probe-' + uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix='sandbox-sync-') as temporary:
        work = Path(temporary)
        with SandboxRuntime(registration, work) as runtime:
            probe = ProbeRuntime(runtime, relative)
            originals = {}
            for role in ('storage', 'coordinator'):
                with runtime.role(role) as outer:
                    originals[role] = outer.git('rev-parse', 'HEAD').strip()
                    outer.make_directory(relative)
                    outer.git('-c', 'init.templateDir=', 'init', outer.guest_root + '/' + relative)
                with probe.role(role) as repo:
                    # Controller transfer metadata must not dirty this probe repo.
                    repo.write_bytes('.gitignore', b'.fleet/\nprotected.txt\n')
                    repo.write_bytes('content.txt', b'original\n')
                    repo.git('add', '.gitignore')
                    repo.git('add', 'content.txt')
                    commit(repo, 'Independent probe seed')
            with probe.role('storage') as source:
                seed = source.git('rev-parse', 'HEAD').strip()
            transfer_commit(probe, 'storage', 'coordinator', seed)
            with probe.role('coordinator') as target:
                target.git('-c', 'core.hooksPath=/dev/null', 'checkout', '--detach', seed)
            with probe.role('storage') as source:
                source.write_bytes('content.txt', b'updated\n')
                source.git('add', 'content.txt')
                baseline = commit(source, 'Fast-forward probe')
            receipt = synchronize_fast_forward(probe, 'storage', 'coordinator', baseline,
                                               seed, work / 'sync-attempt')
            assert receipt['phase'] == 'complete'
            assert receipt['head_ref'] == 'HEAD'
            assert receipt['guest_root'].endswith('/' + relative)
            with probe.role('coordinator') as target:
                assert target.read_bytes('content.txt') == b'updated\n'
                target.write_bytes('protected.txt', b'local ignored content\n')
            print('content_update_verified', flush=True)
            with probe.role('storage') as source:
                source.write_bytes('protected.txt', b'incoming tracked content\n')
                source.git('add', '-f', 'protected.txt')
                collision = commit(source, 'Ignored file collision probe')
            try:
                synchronize_fast_forward(probe, 'storage', 'coordinator', collision,
                                         baseline, work / 'collision-attempt')
            except GuestRepositoryError:
                pass
            else:
                raise AssertionError('Ignored file overwritten')
            incomplete = json.loads((work / 'collision-attempt/receipt.json').read_text())
            assert incomplete['phase'] == 'applying'
            with probe.role('coordinator') as target:
                assert target.git('rev-parse', 'HEAD').strip() == baseline
                assert target.read_bytes('protected.txt') == b'local ignored content\n'
                assert target.read_bytes('content.txt') == b'updated\n'
            print('ignored_collision_preserved_and_journal_incomplete', flush=True)
            with probe.role('coordinator') as target:
                target.write_bytes('.git/MERGE_HEAD', (baseline + '\n').encode())
            try:
                synchronize_fast_forward(probe, 'storage', 'coordinator', baseline,
                                         baseline, work / 'interrupted-attempt')
            except RuntimeError as exc:
                assert 'Unfinished Git operation' in str(exc), str(exc)
            else:
                raise AssertionError('Unfinished merge admitted')
            with probe.role('coordinator') as target:
                assert target.read_bytes('.git/MERGE_HEAD') == (baseline + '\n').encode()
                assert target.git('rev-parse', 'HEAD').strip() == baseline
            print('unfinished_merge_refused_marker_retained', flush=True)
            for role, head in originals.items():
                with runtime.role(role) as outer:
                    assert outer.git('rev-parse', 'HEAD').strip() == head
            print(json.dumps(receipt), flush=True)
        print('sync_live_passed: content updated, ignored collision refused, original HEADs unchanged, VMs stopped')


if __name__ == '__main__':
    main()
