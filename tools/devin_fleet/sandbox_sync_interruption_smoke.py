"""Post-merge/pre-receipt interruption in independent VM probe repositories.

Injected exception, not physical power loss. Preserve outer journals for review.
"""
from contextlib import contextmanager
import json
from pathlib import Path
import uuid

from durable import atomic_write_json
from sandbox_runtime import SandboxRuntime
from sandbox_sync import synchronize_fast_forward
from sandbox_sync_recovery import inspect_sync_recovery
from sandbox_sync_smoke import ProbeRuntime, commit
from sandbox_transfer import transfer_commit


class InjectedInterruption(RuntimeError):
    pass


class InterruptAfterMerge:
    def __init__(self, runtime):
        self.runtime = runtime
        self.registration = runtime.registration
        self.merges = 0

    @contextmanager
    def role(self, role):
        with self.runtime.role(role) as repo:
            owner = self
            class Proxy:
                def __getattr__(self, name):
                    return getattr(repo, name)

                def git(self, *args):
                    result = repo.git(*args)
                    if 'merge' in args:
                        owner.merges += 1
                        raise InjectedInterruption('Applied merge; completion receipt not written')
                    return result
            yield Proxy()


def main():
    registration = json.loads(Path('sandbox-registry.json').read_text())
    registration.update(backend='sandbox', migration_epoch=str(uuid.uuid4()))
    identifier = uuid.uuid4().hex
    relative = '.fleet/interruption-probe-' + identifier
    work = Path.cwd() / ('interruption-evidence-' + identifier)
    work.mkdir(mode=0o700)
    atomic_write_json(work / 'registration.json', registration)
    print('persistent_evidence=' + str(work), flush=True)
    with SandboxRuntime(registration, work) as runtime:
        probe = ProbeRuntime(runtime, relative)
        originals = {}
        for role in ('storage', 'coordinator'):
            with runtime.role(role) as outer:
                originals[role] = outer.git('rev-parse', 'HEAD').strip()
                outer.make_directory(relative)
                outer.git('-c', 'init.templateDir=', 'init', outer.guest_root + '/' + relative)
            with probe.role(role) as repo:
                repo.write_bytes('.gitignore', b'.fleet/\n')
                repo.write_bytes('content.txt', b'before interruption\n')
                repo.git('add', '.gitignore', 'content.txt')
                commit(repo, 'Interruption probe seed')
        with probe.role('storage') as source:
            seed = source.git('rev-parse', 'HEAD').strip()
        transfer_commit(probe, 'storage', 'coordinator', seed)
        with probe.role('coordinator') as target:
            target.git('-c', 'core.hooksPath=/dev/null', 'checkout', '--detach', seed)
        with probe.role('storage') as source:
            source.write_bytes('content.txt', b'applied exactly once\n')
            source.git('add', 'content.txt')
            baseline = commit(source, 'Applied before receipt interruption')
        interrupted = InterruptAfterMerge(probe)
        try:
            synchronize_fast_forward(interrupted, 'storage', 'coordinator', baseline,
                                     seed, work / 'attempt')
        except InjectedInterruption:
            pass
        else:
            raise AssertionError('Expected interruption did not happen')
        assert interrupted.merges == 1
        path = work / 'attempt/receipt.json'
        original = path.read_bytes()
        receipt = json.loads(original)
        assert receipt['phase'] == 'applying'
        print('post_merge_interruption_recorded', flush=True)
        evidence = inspect_sync_recovery(interrupted, original, receipt['operation_id'],
                                         work / 'recovery')
        assert evidence['outcome'] == 'verified_applied'
        assert evidence['replay_permitted'] is False and interrupted.merges == 1
        assert path.read_bytes() == original
        with probe.role('coordinator') as target:
            assert target.read_bytes('content.txt') == b'applied exactly once\n'
            assert target.git('rev-parse', 'HEAD').strip() == baseline
        for role, head in originals.items():
            with runtime.role(role) as outer:
                assert outer.git('rev-parse', 'HEAD').strip() == head
        atomic_write_json(work / 'result.json', {'evidence': evidence, 'merge_count': 1,
                          'original_heads': originals, 'guest_probe_relative': relative})
        print(json.dumps(evidence), flush=True)
    print('interruption_live_passed: applied once, applying receipt retained, recovered observation, VMs stopped', flush=True)


if __name__ == '__main__':
    main()
