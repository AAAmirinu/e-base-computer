"""Fixed one-shot maintenance build/import using the production mechanism."""
import hashlib
import json

import candidate_container_run as runner
from candidate_evidence_binding import bind_candidate
from durable import atomic_write_json
from managed_cli_guard import require_managed_namespace
from run_stdlib_candidate import inputs, DIGEST
from sandbox_candidate_adapter import run_roundtrip
from validation_snapshot_input import _file, load_snapshot
from validation_dispatch_receipt import _pairs
from validation_snapshot_dispatch import UUID

PREFIX = 'maintenance-common-roundtrip-v1'


def main():
    require_managed_namespace()
    registry_raw = _file(runner.ROOT/'sandbox-registry.json', 65536)
    if json.loads(registry_raw, object_pairs_hook=_pairs).get('production_enabled') is not False:
        raise ValueError('Maintenance requires production disabled')
    packet, expected, dispatch_sha = inputs()
    raw, blobs, _ = load_snapshot(runner.ROOT/'stdlib-main-snapshot-6gprve05', DIGEST)
    source = runner.ROOT/'dispatch-7e3e23afef9f4a1d8edd71f7688c3704'
    dispatch = _file(source/'dispatch.json', 8*1024*1024)
    stdout = _file(source/'stdout.log', 8*1024*1024)
    if hashlib.sha256(dispatch).hexdigest() != dispatch_sha:
        raise ValueError('Fixed validation changed')
    def admission():
        if _file(runner.ROOT/'sandbox-registry.json', 65536) != registry_raw:
            raise ValueError('Maintenance registration changed')
        if _file(source/'dispatch.json', 8*1024*1024) != dispatch:
            raise ValueError('Fixed validation changed')
    built = run_roundtrip(packet, expected, dispatch_sha, identity_prefix=PREFIX, admission=admission)
    proof = bind_candidate(raw, DIGEST, blobs, dispatch, stdout, **built,
                           validator_id=UUID, image_id=runner.IMAGE)
    admission()
    work = runner.ROOT/('candidate-attempt-'+hashlib.sha256((PREFIX+':import').encode()).hexdigest()[:32])
    proof.update(phase='maintenance_roundtrip_verified', published=False)
    atomic_write_json(work/'maintenance-proof.json', proof)
    print(json.dumps(dict(evidence=str(work), **proof)), flush=True)


if __name__ == '__main__':
    main()
