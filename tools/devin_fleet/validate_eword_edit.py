"""Validate one digest-bound Devin edit in the credential-free container only."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

from durable import atomic_write_json
from managed_cli_guard import require_managed_namespace
from sandbox_snapshot import persist_source_snapshot
from validation_snapshot_input import load_snapshot, _file
from machine_eword_edit import unique_pairs

ROOT = Path('/home/fleet/controller-validation')
BASE_DIGEST = '47810d95844b90f04844cf85ad8a42a62f91e4c0157beeb9a19836dc12c4f2ea'
INPUT = 'faa71b4ddc1fa8e34dc0c03dc9d21cc300c61663574e0f086abff999545857c8'
CANDIDATE = '9a4b52142e99a7acb226c483a9ce78597e37686b1b635405795ebc80ddb5baaf'
EXPORT = '75ab8262a510ccd00b7d08224ae29adb1bdf64598cd6109cd693303249a5e261'
FIXTURE = '8c8ecea5f594c753a127c41d56231948bfdee9d4770214e1161cc592066d111e'


def main():
    require_managed_namespace()
    origin = ROOT / 'interactive-auth-uy0f_ax6'
    receipt = json.loads(_file(origin / 'receipt.json', 32768), object_pairs_hook=unique_pairs)
    edit = receipt.get('eword_edit', {})
    if (receipt.get('phase') != 'closed' or receipt.get('cleanup_errors') != []
            or receipt.get('network_denied_after') is not True
            or receipt.get('all_vms_stopped') is not True
            or receipt.get('sandbox_id') != '40e32a36-d565-4853-a841-fa3bea9ac648'
            or edit.get('passed') is not True or edit.get('tool_scope_verified') is not True
            or edit.get('candidate_executed') is not False or edit.get('production_admitted') is not False
            or edit.get('input_sha256') != INPUT or edit.get('candidate_sha256') != CANDIDATE
            or edit.get('export_sha256') != EXPORT):
        raise ValueError('Model candidate provenance or cleanup mismatch')
    _, blobs, manifest = load_snapshot(ROOT / 'eword-baseline-xxlcbs8p', BASE_DIGEST)
    entries = {entry['path']: entry for entry in manifest['files']}
    if entries['src/ecomputer.py']['sha256'] != INPUT:
        raise ValueError('Source base mismatch')
    candidate = _file(origin / 'ecomputer.py.candidate', 32768)
    fixture = _file(ROOT / 'fixtures/test_eword_boundary_fixed.py', 32768)
    if hashlib.sha256(candidate).hexdigest() != CANDIDATE or hashlib.sha256(fixture).hexdigest() != FIXTURE:
        raise ValueError('Reviewed artifact digest mismatch')
    before = b'if isclose(digit, e, abs_tol=EPSILON):'
    after = b'if isclose(digit, e, rel_tol=0.0, abs_tol=EPSILON):'
    if blobs[INPUT].count(before) != 1 or candidate != blobs[INPUT].replace(before, after):
        raise ValueError('Candidate is not the reviewed one-line repair')
    replacements = {}
    for name, data in {'src/ecomputer.py': candidate,
                       'tests/test_eword_boundary_regression.py': fixture}.items():
        entry = entries[name]
        digest = hashlib.sha256(data).hexdigest()
        replacements[name] = dict(before=entry['sha256'], after=digest)
        entry.update(sha256=digest, size=len(data))
        blobs[digest] = data
    required = {entry['sha256'] for entry in manifest['files']}
    blobs = {key: value for key, value in blobs.items() if key in required}
    raw = json.dumps(manifest, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    digest = hashlib.sha256(raw).hexdigest()
    work = Path(tempfile.mkdtemp(prefix='eword-repair-', dir=ROOT))
    snapshot = work / 'source-snapshot'
    persist_source_snapshot(snapshot, dict(manifest=manifest, manifest_sha256=digest, blobs=blobs))
    atomic_write_json(work / 'derivation.json', dict(schema=1, base_manifest_sha256=BASE_DIGEST,
        manifest_sha256=digest, model_receipt=str(origin / 'receipt.json'), replacements=replacements,
        source_executed_on_controller=False, role_vm_modified=False, committed=False))
    print('repair_evidence=' + str(work), flush=True)
    subprocess.run(['/usr/bin/python3', '-E', '-s', str(ROOT / 'validation_snapshot_dispatch.py'),
                    '--snapshot', str(snapshot), '--manifest-sha256', digest], check=True)


if __name__ == '__main__':
    main()
