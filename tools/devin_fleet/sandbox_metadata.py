"""Install the controller metadata exclusion omitted by bundle-only migration.

Preserves existing excludes and saves original bytes; never changes source files.
"""
import hashlib
import uuid


def configure_guest_metadata(repo):
    if (repo.path_kind('.git') != 'directory' or
            repo.git('rev-parse', '--absolute-git-dir').strip() != repo.guest_root + '/.git'):
        raise RuntimeError('Standalone guest Git directory required')
    if repo.git('ls-files', '-z', '--', '.fleet'):
        raise RuntimeError('Tracked controller metadata requires inspection')
    info_kind = repo.path_kind('.git/info')
    if info_kind not in ('directory', 'missing'):
        raise RuntimeError('Guest Git info directory required')
    if info_kind == 'missing':
        repo.make_directory('.git/info')
    kind = repo.path_kind('.git/info/exclude')
    if kind not in ('regular', 'missing'):
        raise RuntimeError('Linked or special exclude file refused')
    previous = repo.read_bytes('.git/info/exclude', max_bytes=30 * 1024) if kind == 'regular' else b''
    rules = [line for line in previous.splitlines() if line and not line.startswith(b'#')]
    if rules and rules[-1] == b'/.fleet/':
        return {'changed': False, 'after_sha256': hashlib.sha256(previous).hexdigest()}
    head = repo.git('rev-parse', 'HEAD').strip()
    backup = '.fleet/metadata-config-' + uuid.uuid4().hex
    repo.make_directory(backup)
    repo.write_bytes(backup + '/exclude.before', previous)
    replacement = previous + b'\n/.fleet/\n'
    repo.write_bytes('.git/info/exclude', replacement)
    digest = hashlib.sha256(replacement).hexdigest()
    if repo.sha256('.git/info/exclude', max_bytes=32 * 1024) != digest:
        raise RuntimeError('Exclude file verification failed; preserve backup')
    if repo.git('rev-parse', 'HEAD').strip() != head:
        raise RuntimeError('HEAD changed during metadata configuration')
    return {'changed': True, 'before_sha256': hashlib.sha256(previous).hexdigest(),
            'after_sha256': digest, 'backup': backup + '/exclude.before'}
