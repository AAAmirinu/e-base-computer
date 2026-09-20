"""Offline fixed maintenance evidence check; never start a VM or release a fence."""
import json
from pathlib import Path
import tempfile

from candidate_evidence_binding import bind_candidate
from durable import atomic_write_json, _sync_directory
from validation_snapshot_input import load_snapshot, _file


def main():
    root = Path('/home/fleet/controller-validation')
    digest = '6039785fee9ba2a0425c41b6999e0fa082abe49310f47e0124ab9d204ad070ff'
    raw, blobs, _ = load_snapshot(root/'stdlib-main-snapshot-6gprve05', digest)
    dispatch = root/'dispatch-7e3e23afef9f4a1d8edd71f7688c3704'
    build = root/'stdlib-candidate-as9h24h6'
    imported = root/'stdlib-import-_7gqahb2'
    result = bind_candidate(raw, digest, blobs,
        _file(dispatch/'dispatch.json', 8*1024*1024), _file(dispatch/'stdout.log', 8*1024*1024),
        _file(build/'receipt.json', 8*1024*1024), _file(imported/'receipt.json', 8*1024*1024),
        _file(build/'candidate.bundle', 16*1024*1024),
        validator_id='84a0fc99-4cbb-4383-a1df-4c22bbe0d2e6',
        image_id='sha256:cee9fe9272c17a34c0b1620485843ff67431dcc18d2e0f7380581fe28f5aeaf4')
    work = Path(tempfile.mkdtemp(prefix='candidate-binding-', dir=root))
    _sync_directory(root)
    atomic_write_json(work/'receipt.json', result)
    print(json.dumps(dict(evidence=str(work/'receipt.json'), binding=result)))


if __name__ == '__main__':
    main()
