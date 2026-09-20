"""Prepare actual stopped-fleet metadata in a VM; no model/project execution."""
import json
from pathlib import Path
import sys
import tempfile

import fleet
from sandbox_runtime import SandboxRuntime
from sandbox_repository import GuestRepositoryError


def main():
    source = Path(sys.argv[1])
    state = json.loads((source / 'state.json').read_text(encoding='utf-8'))
    roles = json.loads((source / 'roles.json').read_text(encoding='utf-8'))
    registration = json.loads(Path('sandbox-registry.json').read_text())
    with tempfile.TemporaryDirectory(prefix='guest-turn-') as work:
        with SandboxRuntime(registration, Path(work)) as runtime:
            with runtime.role('machine') as repo:
                prepared = fleet.prepare_guest_turn(source, repo, 'machine', roles['machine'], state)
                raw = repo.read_bytes(prepared['relative'] + '/context.json', max_bytes=512 * 1024)
                context = json.loads(raw)
                for key in ('reports', 'candidates', 'shared_notes'):
                    assert context[key] == state.get(key, {})
                assert '--resume' not in prepared['args']
                assert fleet.sha(repo) == prepared['base']
                print('actual_turn_prepared ' + json.dumps({
                    'relative': prepared['relative'], 'context_bytes': len(raw),
                    'context_sha256': repo.sha256(prepared['relative'] + '/context.json'),
                    'base': prepared['base'], 'round': prepared['round']}))
                target = prepared['relative'] + '/unchanged.bin'
                repo.write_bytes(target, b'original')
                original_write = repo.write_bytes
                def corrupt_part(path, data):
                    if path.endswith('/0'):
                        data = b'X' + data[1:]
                    return original_write(path, data)
                repo.write_bytes = corrupt_part
                try:
                    repo.write_large_bytes(target, b'a' * 40000)
                except GuestRepositoryError:
                    assert repo.controller.fenced
                else:
                    raise AssertionError('Corrupted transfer accepted')
            with runtime.role('machine') as repo:
                assert repo.read_bytes(target) == b'original'
                print('corrupt_transfer_preserved_original')
        print('guest_turn_live_passed: complete metadata, no old session adoption, unchanged HEAD, final stop')


if __name__ == '__main__':
    main()
