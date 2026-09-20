"""Build and independently import one validated turn; never publish or resume."""
import base64
import hashlib
import json

import candidate_container_run as runner
from candidate_packet import MODULES, prepare_build, prepare_import
from candidate_turn_admission import make_admission
from candidate_review_store import _exclusive_bytes
from candidate_evidence_binding import bind_turn_candidate
from durable import _sync_directory
from managed_cli_guard import require_managed_namespace
from turn_validation_result import bind_result, same_json
from validation_snapshot_input import _file
from validation_dispatch_receipt import _pairs
from validation_snapshot_dispatch import UUID


def build_and_import(binding, evidence, *, registration, parent_bundle,
                     parent_bundle_sha256, parent_ref, admission_factory=None):
    """Use as a partial-bound adapter for sandbox_one_turn.

Parent bundle bytes/digest/ref are supplied by trusted deployment, never by the
model. Both attempts have deterministic identities: restarting cannot resend.
"""
    require_managed_namespace()
    binding = json.loads(json.dumps(binding, allow_nan=False))
    registration = json.loads(json.dumps(registration, allow_nan=False))
    if admission_factory is None:
        admission_factory = make_admission
    elif admission_factory is not make_admission:
        from prepared_candidate_trial_admission import make_admission as trial_admission
        if admission_factory is not trial_admission:
            raise ValueError('Only production or fixed prepared-trial admission is allowed')
    admission = admission_factory(registration, binding)
    if not callable(admission):
        raise ValueError('Candidate admission callback required')
    fields = {'manifest_raw', 'manifest_sha256', 'blobs', 'dispatch_raw', 'stdout_raw',
              'validator_id', 'image_id'}
    if not isinstance(evidence, dict) or set(evidence) != fields:
        raise ValueError('Exact raw validation and snapshot evidence required')
    evidence = dict(evidence, blobs=dict(evidence['blobs']))
    if evidence['validator_id'] != UUID or evidence['image_id'] != runner.IMAGE:
        raise ValueError('Fixed credential-free Git validator required')
    result = bind_result(binding, evidence['dispatch_raw'], evidence['stdout_raw'],
                         validator_id=UUID, image_id=runner.IMAGE)
    if (result['outcome'] != 'test_command_succeeded'
            or evidence['manifest_sha256'] != binding['manifest_sha256']):
        raise ValueError('Successful exact turn validation required')
    modules = {name: _file(runner.ROOT/(name+'.py'), 32768).decode('utf-8')
               for name in sorted(MODULES)}
    packet, expected = prepare_build(evidence['manifest_raw'], evidence['manifest_sha256'],
        evidence['blobs'], parent_bundle, parent_bundle_sha256, parent_ref, modules)
    if expected['base'] != binding['base']:
        raise ValueError('Candidate parent differs from bound turn')
    dispatch_sha = hashlib.sha256(evidence['dispatch_raw']).hexdigest()
    built = run_roundtrip(packet, expected, dispatch_sha,
        identity_prefix=binding['migration_epoch']+':'+binding['operation_id'], admission=admission)
    bind_turn_candidate(binding, registration, **evidence, **built)
    admission()
    return built


def run_roundtrip(packet, expected, dispatch_sha, *, identity_prefix, admission):
    """Trusted low-level mechanism only; caller must bind turn or maintenance evidence."""
    require_managed_namespace()
    if not isinstance(identity_prefix, str) or not identity_prefix or not callable(admission):
        raise ValueError('Explicit stable attempt identity and admission required')
    def attempt(mode, payload, origin=None):
        identity = identity_prefix+':'+mode
        work = runner.ROOT/('candidate-attempt-'+hashlib.sha256(identity.encode()).hexdigest()[:32])
        completed = runner.execute(payload, work, admission=admission)
        raw = _file(work/'stdout.json', 24*1024*1024)
        guest = json.loads(raw, object_pairs_hook=_pairs)
        lifecycle = json.loads(_file(work/'receipt.json', 65536), object_pairs_hook=_pairs)
        if (completed.get('directory') != str(work) or not same_json(completed.get('guest'), guest)
                or lifecycle.get('phase') != 'stopped_result'
                or lifecycle.get('all_vms_stopped') is not True
                or lifecycle.get('image_id') != runner.IMAGE
                or lifecycle.get('packet_sha256') != hashlib.sha256(payload).hexdigest()
                or lifecycle.get('stdout_sha256') != hashlib.sha256(raw).hexdigest()):
            raise ValueError('Stopped attempt evidence mismatch')
        candidate = guest.pop('candidate')
        bundle = base64.b64decode(candidate['bundle'], validate=True)
        record = dict(schema=1, phase='candidate_recovered' if mode == 'build' else 'import_verified',
            image_id=runner.IMAGE, all_vms_stopped=True, expected=expected,
            mode='build' if mode == 'build' else 'import_check',
            origin_receipt_sha256=origin, validation_dispatch_sha256=dispatch_sha,
            published=False, production_accepted=False, candidate=candidate['metadata'],
            container_evidence=guest)
        if not 0 < len(bundle) <= 16*1024*1024:
            raise ValueError('Oversize or empty recovered bundle')
        record_raw = json.dumps(record, sort_keys=True, allow_nan=False).encode()
        _exclusive_bytes(work/'candidate.bundle', bundle)
        _exclusive_bytes(work/'candidate.json', record_raw)
        _sync_directory(work)
        return record_raw, bundle, candidate['metadata']

    build_raw, bundle, metadata = attempt('build', packet)
    import_packet = prepare_import(packet, bundle, metadata)
    import_raw, recovered, _ = attempt('import', import_packet, hashlib.sha256(build_raw).hexdigest())
    if recovered != bundle:
        raise ValueError('Independent import returned different bundle')
    return dict(build_raw=build_raw, import_raw=import_raw, bundle=bundle)
