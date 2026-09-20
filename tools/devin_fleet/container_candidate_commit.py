"""Trusted candidate builder, callable ONLY in a checked credential-free container.

Caller supplies a digest-verified parent bundle and validated snapshot. No code
from that snapshot is executed here. Failed fresh directories are never reused.
"""
import hashlib
import os
import re
from pathlib import Path
import subprocess

from sandbox_snapshot_receiver import materialize_snapshot
from snapshot_git_tree import expected_tree, verify_commit_tree
from sandbox_snapshot_receiver import validate_snapshot


def verify_fresh_config(raw):
    expected = {b'core.repositoryformatversion\n0', b'core.filemode\ntrue',
                b'core.bare\nfalse', b'core.logallrefupdates\ntrue'}
    if not isinstance(raw, bytes) or not raw.endswith(b'\0'):
        raise ValueError('Missing fresh Git configuration')
    entries = raw[:-1].split(b'\0')
    if len(entries) != len(expected) or set(entries) != expected:
        raise ValueError('Unexpected template or effective Git configuration')


def verify_import(raw, digest, blobs, bundle, metadata):
    """Import into a second fresh repository; do not checkout or execute source."""
    if (os.getuid() != 65532 or not Path('/.dockerenv').is_file()
            or os.environ.get('HOME') != '/work'
            or set(os.environ) - {'PATH', 'HOME', 'LANG', 'LC_CTYPE'}):
        raise RuntimeError('Checked credential-free container required')
    manifest = validate_snapshot(raw, digest, blobs)
    expected = expected_tree(raw, digest, blobs)
    if (metadata.get('tree') != expected['tree'] or metadata.get('parent') != expected['base']
            or metadata.get('manifest_sha256') != digest
            or not isinstance(bundle, bytes) or not 0 < len(bundle) <= 16*1024*1024
            or len(bundle) != metadata.get('bundle_bytes')
            or hashlib.sha256(bundle).hexdigest() != metadata.get('bundle_sha256')):
        raise ValueError('Imported candidate binding mismatch')
    commit = metadata.get('commit')
    if not isinstance(commit, str) or len(commit) != 40 or any(c not in '0123456789abcdef' for c in commit):
        raise ValueError('Canonical commit required')
    root = Path('/work/import-check')
    root.mkdir(mode=0o700)
    path = Path('/work/import.bundle')
    with path.open('xb') as stream:
        stream.write(bundle)
    def git(*args):
        return subprocess.run(['/usr/bin/git', *args], check=True, capture_output=True,
                              stdin=subprocess.DEVNULL, timeout=30).stdout
    if git('config', '--list', '--name-only').strip():
        raise RuntimeError('Unexpected inherited Git configuration')
    git('init', str(root))
    verify_fresh_config(git('-C', str(root), 'config', '--list', '--null'))
    hooks = root/'.git/hooks'
    if hooks.exists() and any(p.is_symlink() or not p.is_file() or not p.name.endswith('.sample') for p in hooks.iterdir()):
        raise RuntimeError('Unexpected active Git hook')
    if git('-C', str(root), 'rev-parse', '--show-object-format').strip() != b'sha1':
        raise RuntimeError('SHA-1 repository required')
    git('-C', str(root), 'bundle', 'verify', str(path))
    if git('bundle', 'list-heads', str(path)).decode().strip() != commit+' refs/heads/candidate':
        raise RuntimeError('Unexpected bundle heads')
    git('-C', str(root), 'fetch', '--no-tags', '--no-write-fetch-head', str(path), 'refs/heads/candidate')
    if git('-C', str(root), 'rev-list', '--parents', '-n', '1', commit).decode().strip() != commit+' '+expected['base']:
        raise RuntimeError('Imported parent mismatch')
    verify_commit_tree(raw, digest, blobs, observed_format='sha1',
                       observed_tree=git('-C', str(root), 'rev-parse', commit+'^{tree}').decode().strip())
    actual_paths = git('-C', str(root), 'ls-tree', '-r', '--name-only', '-z', commit).split(b'\0')
    if actual_paths[-1:] != [b''] or set(actual_paths[:-1]) != {e['path'].encode() for e in manifest['files']}:
        raise RuntimeError('Imported paths mismatch')
    for entry in manifest['files']:
        data = git('-C', str(root), 'cat-file', 'blob', commit+':'+entry['path'])
        if len(data) != entry['size'] or hashlib.sha256(data).hexdigest() != entry['sha256']:
            raise RuntimeError('Imported blob differs from validated bytes')
    return dict(metadata, import_verified=True, verified_file_count=len(manifest['files']),
                checked_out=False, source_executed=False), bundle


def build_candidate(raw, digest, blobs, bundle, bundle_sha256, parent_ref):
    # The runtime owner must still verify container config, boundary, and cleanup.
    if (os.getuid() != 65532 or not Path('/.dockerenv').is_file()
            or os.environ.get('HOME') != '/work'
            or set(os.environ) - {'PATH', 'HOME', 'LANG', 'LC_CTYPE'}):
        raise RuntimeError('Checked credential-free container required')
    expected = expected_tree(raw, digest, blobs)
    if (not isinstance(bundle, bytes) or not 0 < len(bundle) <= 16*1024*1024
            or hashlib.sha256(bundle).hexdigest() != bundle_sha256
            or not isinstance(parent_ref, str)
            or re.fullmatch(r'refs/heads/[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*', parent_ref) is None):
        raise ValueError('Fixed parent bundle contract mismatch')
    parent_path = Path('/work/parent.bundle')
    with parent_path.open('xb') as stream:
        stream.write(bundle)
    root = '/work/candidate'
    materialize_snapshot('/work', 'candidate', raw, digest, blobs)

    def git(*args):
        result = subprocess.run(['/usr/bin/git', *args], check=True, capture_output=True,
                                timeout=30, stdin=subprocess.DEVNULL)
        if len(result.stdout) + len(result.stderr) > 1024*1024:
            raise RuntimeError('Oversize Git output')
        return result.stdout

    if git('config', '--list', '--name-only').strip():
        raise RuntimeError('Unexpected inherited Git configuration')
    git('init', root)
    verify_fresh_config(git('-C', root, 'config', '--list', '--null'))
    hooks = Path(root)/'.git/hooks'
    if hooks.exists() and any(p.is_symlink() or not p.is_file() or not p.name.endswith('.sample')
                              for p in hooks.iterdir()):
        raise RuntimeError('Unexpected active Git hook')
    if git('-C', root, 'rev-parse', '--show-object-format').strip() != b'sha1':
        raise RuntimeError('SHA-1 repository required')
    git('-C', root, 'bundle', 'verify', str(parent_path))
    if git('bundle', 'list-heads', str(parent_path)).decode().strip() != expected['base'] + ' ' + parent_ref:
        raise RuntimeError('Parent bundle ref mismatch')
    git('-C', root, 'fetch', '--no-tags', '--no-write-fetch-head', str(parent_path), parent_ref)
    if git('-C', root, 'rev-parse', expected['base']+'^{commit}').decode().strip() != expected['base']:
        raise RuntimeError('Parent identity mismatch')
    git('-C', root, 'symbolic-ref', 'HEAD', 'refs/heads/candidate')
    git('-C', root, 'update-ref', 'HEAD', expected['base'], '0'*40)
    # Fresh private output only. Never reset or overwrite a user's working tree.
    git('-C', root, 'reset', '--mixed', expected['base'])
    git('-C', root, 'add', '--all')
    verify_commit_tree(raw, digest, blobs, observed_format='sha1',
                       observed_tree=git('-C', root, 'write-tree').decode().strip())
    git('-C', root, 'config', 'user.name', 'E-base Candidate Builder')
    git('-C', root, 'config', 'user.email', 'candidate@localhost')
    git('-C', root, 'commit', '-m', 'Candidate from validated source snapshot')
    commit = git('-C', root, 'rev-parse', 'HEAD').decode().strip()
    if git('-C', root, 'rev-list', '--parents', '-n', '1', 'HEAD').decode().strip() != commit+' '+expected['base']:
        raise RuntimeError('Candidate parent mismatch')
    verify_commit_tree(raw, digest, blobs, observed_format='sha1',
                       observed_tree=git('-C', root, 'rev-parse', 'HEAD^{tree}').decode().strip())
    if git('-C', root, 'status', '--porcelain', '--untracked-files=all'):
        raise RuntimeError('Candidate worktree not clean')
    output = Path('/work/candidate.bundle')
    if output.exists():
        raise RuntimeError('Fresh bundle destination required')
    git('-C', root, 'bundle', 'create', str(output), 'refs/heads/candidate')
    git('-C', root, 'bundle', 'verify', str(output))
    if output.stat().st_size > 16*1024*1024:
        raise RuntimeError('Candidate bundle exceeds bound')
    payload = output.read_bytes()
    return dict(commit=commit, parent=expected['base'], tree=expected['tree'],
                manifest_sha256=digest, bundle_sha256=hashlib.sha256(payload).hexdigest(),
                bundle_bytes=len(payload), production_accepted=False, published=False), payload
