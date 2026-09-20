"""One fixed maintenance import through the common runner; no production turn."""
import base64
import hashlib
import json

import candidate_container_run as runner
from candidate_packet import prepare_import
from durable import atomic_write_json
from managed_cli_guard import require_managed_namespace
from run_stdlib_candidate import inputs
from validation_snapshot_input import _file
from validation_dispatch_receipt import _pairs
from turn_validation_result import same_json

ORIGIN = runner.ROOT/'stdlib-candidate-as9h24h6'
ORIGIN_SHA = '2241058772c409fd47360951e0fd49ce0623ae389095d9163a47e2f645f6f872'
BUNDLE_SHA = '9b89d4a565bb650d66962cf1b5af7efe2219c3ab90d455412170f446aafb2406'
WORK = runner.ROOT/('candidate-attempt-'+hashlib.sha256(b'maintenance-common-import-v1').hexdigest()[:32])


def main():
    require_managed_namespace()
    registry_raw = _file(runner.ROOT/'sandbox-registry.json', 65536)
    registry = json.loads(registry_raw, object_pairs_hook=_pairs)
    if registry.get('production_enabled') is not False:
        raise ValueError('Maintenance requires disabled production')
    origin_raw = _file(ORIGIN/'receipt.json', 1024*1024)
    bundle = _file(ORIGIN/'candidate.bundle', 16*1024*1024)
    if (hashlib.sha256(origin_raw).hexdigest() != ORIGIN_SHA
            or hashlib.sha256(bundle).hexdigest() != BUNDLE_SHA):
        raise ValueError('Fixed preserved candidate required')
    origin = json.loads(origin_raw, object_pairs_hook=_pairs)
    packet, expected, dispatch_sha = inputs()
    if (origin.get('phase') != 'candidate_recovered' or origin.get('all_vms_stopped') is not True
            or origin.get('validation_dispatch_sha256') != dispatch_sha):
        raise ValueError('Original stopped candidate validation required')
    metadata = origin['candidate']
    packet = prepare_import(packet, bundle, metadata)
    def admission():
        if _file(runner.ROOT/'sandbox-registry.json', 65536) != registry_raw:
            raise ValueError('Maintenance registration changed')
        if _file(ORIGIN/'receipt.json', 1024*1024) != origin_raw:
            raise ValueError('Original candidate changed')
    result = runner.execute(packet, WORK, admission=admission)
    candidate = result['guest']['candidate']
    observed = candidate['metadata']
    if (not same_json({key: observed.get(key) for key in metadata}, metadata)
            or observed.get('import_verified') is not True
            or type(observed.get('verified_file_count')) is not int
            or observed['verified_file_count'] != expected['file_count']
            or observed.get('checked_out') is not False or observed.get('source_executed') is not False
            or base64.b64decode(candidate['bundle'], validate=True) != bundle):
        raise ValueError('Fixed candidate independent import mismatch')
    admission()
    lifecycle_raw = _file(WORK/'receipt.json', 65536)
    stdout_raw = _file(WORK/'stdout.json', 24*1024*1024)
    lifecycle = json.loads(lifecycle_raw, object_pairs_hook=_pairs)
    if (lifecycle.get('phase') != 'stopped_result' or lifecycle.get('all_vms_stopped') is not True
            or lifecycle.get('packet_sha256') != hashlib.sha256(packet).hexdigest()
            or lifecycle.get('stdout_sha256') != hashlib.sha256(stdout_raw).hexdigest()
            or not same_json(json.loads(stdout_raw, object_pairs_hook=_pairs), result['guest'])):
        raise ValueError('Saved common runner evidence mismatch')
    proof = dict(schema=1, phase='maintenance_import_verified', candidate=observed,
                 validation_dispatch_sha256=dispatch_sha, origin_receipt_sha256=ORIGIN_SHA,
                 container_id=result['guest']['container_id'], production_accepted=False,
                 turn_bound=False, published=False,
                 runner_receipt_sha256=hashlib.sha256(lifecycle_raw).hexdigest(),
                 stdout_sha256=hashlib.sha256(stdout_raw).hexdigest())
    atomic_write_json(WORK/'maintenance-proof.json', proof)
    print(json.dumps(dict(evidence=str(WORK), **proof)), flush=True)


if __name__ == '__main__':
    main()
