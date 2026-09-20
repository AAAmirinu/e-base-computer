"""Derive and validate a three-file repair; never import candidate source here."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

from durable import atomic_write_json
from sandbox_snapshot import persist_source_snapshot
from validation_snapshot_input import load_snapshot, _file
from managed_cli_guard import require_managed_namespace

ROOT = Path('/home/fleet/controller-validation')
BASE_DIGEST = '2c4008d2837858e8e733eb943335a564da65c8a4723becc3456cd84b438c73eb'
BASE = ROOT/'snapshot-evidence-e4417f75b0804a8cbcbcb38c897c3ebb/source-snapshot'
ORIGINAL = {
    'guest/stdlib/earray.epu': '2c3628c49cb428f3935a89b5344bc83eaf231a4a63e33c9d64898760637d3276',
    'docs/fleet/stdlib/earray_v0.md': 'bde535a2cddb1b424d1169d80d20576d157ee8fa838178792f3f6ff270ab572a',
    'tests/test_stdlib_earray.py': '5bf728eddd72327c15762d28122855e6f22b5f90bdf11c80b17ebe921130c3be',
}


def main():
    require_managed_namespace()
    _, blobs, manifest = load_snapshot(BASE, BASE_DIGEST)
    entries = {entry['path']:entry for entry in manifest['files']}
    replacements = {}
    for relative, original in ORIGINAL.items():
        if entries[relative]['sha256'] != original:
            raise RuntimeError('Local repair base differs from frozen source snapshot')
        data = _file(ROOT/'earray-repair-input'/relative, 1024*1024)
        digest = hashlib.sha256(data).hexdigest()
        if digest == original:
            raise RuntimeError('Expected repair input is unchanged')
        entries[relative].update(sha256=digest, size=len(data))
        blobs[digest] = data
        replacements[relative] = {'before':original, 'after':digest}
    required = {entry['sha256'] for entry in manifest['files']}
    blobs = {digest:blobs[digest] for digest in required}
    canonical = json.dumps(manifest, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    digest = hashlib.sha256(canonical).hexdigest()
    work = Path(tempfile.mkdtemp(prefix='earray-repair-', dir=ROOT))
    snapshot = work/'source-snapshot'
    persist_source_snapshot(snapshot, {'manifest':manifest, 'manifest_sha256':digest, 'blobs':blobs})
    atomic_write_json(work/'derivation.json', {'schema':1, 'base_manifest_sha256':BASE_DIGEST,
        'manifest_sha256':digest, 'replacements':replacements, 'source_executed_on_controller':False,
        'role_vm_modified':False, 'committed':False})
    print('repair_evidence='+str(work), flush=True)
    subprocess.run(['/usr/bin/python3', '-E', '-s', str(ROOT/'validation_snapshot_dispatch.py'),
        '--snapshot', str(snapshot), '--manifest-sha256', digest], check=True)


if __name__ == '__main__':
    main()
