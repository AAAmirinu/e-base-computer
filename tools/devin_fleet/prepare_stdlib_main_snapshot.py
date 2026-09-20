"""Build inert validation input from pinned public main plus six reviewed files.

Trusted maintenance utility; never imports or executes candidate source.
No Git writes, commits, pushes, archive extraction, or network operations.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

BASE = '616ad6b343a58651eba4310123ab267cd74fa2b7'
ADDITIONS = (
    'docs/fleet/stdlib/earray_v0.md',
    'examples/stdlib/vector_dot.epu',
    'guest/stdlib/earray.epu',
    'src/guest_stdlib.py',
    'tests/test_guest_stdlib.py',
    'tests/test_stdlib_earray.py',
)


def main():
    root = Path(__file__).resolve().parents[2]
    repo = root / '.ai/devin-fleet-run/pr-stdlib-main'

    def git(*args):
        return subprocess.run(['git', '-C', str(repo), *args], check=True,
                              capture_output=True, timeout=30).stdout

    if git('rev-parse', 'HEAD').decode().strip() != BASE:
        raise RuntimeError('Candidate base changed')
    if git('diff', '--name-only', 'HEAD'):
        raise RuntimeError('Unexpected tracked changes')
    others = git('ls-files', '--others', '--exclude-standard', '-z').decode().split('\0')
    if set(filter(None, others)) != set(ADDITIONS):
        raise RuntimeError('Candidate additions differ from reviewed scope')
    files, blobs, new_bytes = [], {}, {}

    def add(path, mode, data):
        if len(data) > 1024 * 1024:
            raise RuntimeError('Oversize input')
        parts = path.split('/')
        if (mode not in ('100644', '100755') or
                any(p in ('', '.', '..', '.git', '.devin', '.fleet') for p in parts) or
                parts[0] in ('private_materials', '.env') or '\\' in path or ':' in path):
            raise RuntimeError('Unsafe source entry')
        digest = hashlib.sha256(data).hexdigest()
        files.append(dict(path=path, mode=mode, sha256=digest, size=len(data)))
        blobs[digest] = data

    for item in git('ls-tree', '-rz', BASE).split(b'\0'):
        if not item:
            continue
        meta, name = item.split(b'\t', 1)
        mode, kind, oid = meta.decode().split()
        if kind != 'blob':
            raise RuntimeError('Non-blob source object')
        add(name.decode('utf-8'), mode, git('cat-file', 'blob', oid))
    for name in ADDITIONS:
        path = repo / name
        if path.resolve() != path.absolute() or not path.is_file():
            raise RuntimeError('Linked or missing candidate input')
        data = path.read_bytes()
        new_bytes[name] = data
        add(name, '100644', data)
    files.sort(key=lambda entry: entry['path'])
    if (len(files) > 2048 or len({f['path'] for f in files}) != len(files) or
            sum(f['size'] for f in files) > 16 * 1024 * 1024):
        raise RuntimeError('Snapshot inventory exceeds limits')
    if any((repo / name).read_bytes() != data for name, data in new_bytes.items()):
        raise RuntimeError('Candidate changed during capture')
    manifest = dict(schema=1, base=BASE, files=files)
    raw = json.dumps(manifest, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    digest = hashlib.sha256(raw).hexdigest()
    output = Path(tempfile.mkdtemp(prefix='stdlib-main-snapshot-', dir=root / '.ai'))
    (output / 'blobs').mkdir()
    for key, data in blobs.items():
        (output / 'blobs' / key).write_bytes(data)
    (output / 'manifest.json').write_bytes(raw)
    print(json.dumps(dict(snapshot=str(output), manifest_sha256=digest,
                          base=BASE, file_count=len(files), source_executed=False)))


if __name__ == '__main__':
    main()
