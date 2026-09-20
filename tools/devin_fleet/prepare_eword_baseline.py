"""Construct inert public-main boundary reproduction from an existing pinned snapshot.

Trusted maintenance utility. Does not import or execute project/test code.
Removes the six independently staged stdlib additions; preserves every main blob.
"""
import hashlib
import json
from pathlib import Path
import tempfile

BASE = '616ad6b343a58651eba4310123ab267cd74fa2b7'
SOURCE_DIGEST = '6039785fee9ba2a0425c41b6999e0fa082abe49310f47e0124ab9d204ad070ff'
ADDITIONS = {
    'docs/fleet/stdlib/earray_v0.md', 'examples/stdlib/vector_dot.epu',
    'guest/stdlib/earray.epu', 'src/guest_stdlib.py',
    'tests/test_guest_stdlib.py', 'tests/test_stdlib_earray.py',
}


def main():
    root = Path(__file__).resolve().parents[2]
    source = root / '.ai/stdlib-main-snapshot-6gprve05'
    raw = (source / 'manifest.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_DIGEST:
        raise ValueError('Pinned source manifest mismatch')
    manifest = json.loads(raw)
    if manifest['base'] != BASE or len(manifest['files']) != 121:
        raise ValueError('Unexpected baseline inventory')
    if not ADDITIONS.issubset({entry['path'] for entry in manifest['files']}):
        raise ValueError('Expected additions missing')
    files, blobs = [], {}
    for entry in manifest['files']:
        if entry['path'] in ADDITIONS:
            continue
        data = (source / 'blobs' / entry['sha256']).read_bytes()
        if len(data) != entry['size'] or hashlib.sha256(data).hexdigest() != entry['sha256']:
            raise ValueError('Source blob mismatch')
        files.append(entry)
        blobs[entry['sha256']] = data
    fixture = (root / 'tools/devin_fleet/fixtures/test_eword_boundary_regression.py').read_bytes()
    digest = hashlib.sha256(fixture).hexdigest()
    files.append(dict(path='tests/test_eword_boundary_regression.py', mode='100644',
                      sha256=digest, size=len(fixture)))
    blobs[digest] = fixture
    files.sort(key=lambda entry: entry['path'])
    if len({entry['path'] for entry in files}) != 116:
        raise ValueError('Duplicate baseline path')
    raw = json.dumps(dict(schema=1, base=BASE, files=files), sort_keys=True,
                     separators=(',', ':'), ensure_ascii=False).encode()
    output = Path(tempfile.mkdtemp(prefix='eword-baseline-', dir=root / '.ai'))
    (output / 'blobs').mkdir()
    for key, data in blobs.items():
        (output / 'blobs' / key).write_bytes(data)
    (output / 'manifest.json').write_bytes(raw)
    print(json.dumps(dict(snapshot=str(output), manifest_sha256=hashlib.sha256(raw).hexdigest(),
                          base=BASE, file_count=len(files), source_executed=False)))


if __name__ == '__main__':
    main()
