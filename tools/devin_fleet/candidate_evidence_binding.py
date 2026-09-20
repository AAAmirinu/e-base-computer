"""Link validation, isolated commit, and re-import evidence; never release a fence."""
import hashlib
import json
import re
import uuid

from validation_dispatch_receipt import _pairs, parse_summary
from snapshot_git_tree import expected_tree
from turn_validation_result import same_json, bind_result
from sandbox_turn_fence import ROLES


def _read(raw):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= 8*1024*1024:
        raise ValueError('Bounded controller-owned evidence required')
    def reject(value):
        raise ValueError('Nonfinite evidence number')
    value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=reject)
    if not isinstance(value, dict) or type(value.get('schema')) is not int or value['schema'] != 1:
        raise ValueError('Unsupported evidence schema')
    return value


def _hex(value, length):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{%d}' % length, value) is not None


def _mapping(value):
    if not isinstance(value, dict):
        raise ValueError('Evidence object required')
    return value


def bind_candidate(manifest_raw, manifest_sha256, blobs, dispatch_raw, stdout_raw,
                   build_raw, import_raw, bundle, *, validator_id, image_id):
    """Caller must supply protected controller evidence, not model-provided claims.

This links one snapshot to a recovered/imported commit, not a model turn or a
current runtime state. Test command success does not imply semantic acceptance.
"""
    if not isinstance(validator_id, str) or str(uuid.UUID(validator_id)) != validator_id:
        raise ValueError('Canonical validator ID required')
    if not isinstance(image_id, str) or not re.fullmatch('sha256:[0-9a-f]{64}', image_id):
        raise ValueError('Pinned image required')
    expected = expected_tree(manifest_raw, manifest_sha256, blobs)
    dispatch, build, imported = map(_read, (dispatch_raw, build_raw, import_raw))
    summary = parse_summary(stdout_raw, manifest_sha256, image_id, expected['base'])
    validator = summary['receipt']
    test = _mapping(validator.get('test'))
    boundary = _mapping(validator.get('boundary'))
    if (dispatch.get('phase') != 'complete' or type(dispatch.get('returncode')) is not int
            or dispatch['returncode'] != 0 or dispatch.get('sandbox_id') != validator_id
            or dispatch.get('image_id') != image_id or dispatch.get('manifest_sha256') != manifest_sha256
            or dispatch.get('base') != expected['base'] or dispatch.get('validation_passed') is not False
            or dispatch.get('validation_vm_stopped') is not True
            or dispatch.get('stdout_sha256') != hashlib.sha256(stdout_raw).hexdigest()
            or not same_json(dispatch.get('runner_summary'), summary)
            or validator.get('test_command_succeeded') is not True
            or boundary.get('observations_verified') is not True
            or boundary.get('full_isolation_accepted') is not False
            or test.get('reason') != 'exited' or type(test.get('returncode')) is not int
            or test['returncode'] != 0 or type(test.get('reported_test_count')) is not int
            or test['reported_test_count'] <= 0 or not _hex(test.get('output_sha256'), 64)):
        raise ValueError('Validation evidence mismatch or unsuccessful command')
    dispatch_sha = hashlib.sha256(dispatch_raw).hexdigest()
    containers = [validator['container_id']]
    for record, phase in ((build, 'candidate_recovered'), (imported, 'import_verified')):
        if (record.get('phase') != phase or record.get('image_id') != image_id
                or record.get('all_vms_stopped') is not True
                or record.get('production_accepted') is not False or record.get('published') is not False
                or record.get('validation_dispatch_sha256') != dispatch_sha
                or not same_json(record.get('expected'), expected)):
            raise ValueError('Candidate evidence or shutdown mismatch')
        container = _mapping(record.get('container_evidence'))
        boundary = _mapping(container.get('boundary'))
        if (container.get('image_id') != image_id or container.get('passed') is not True
                or container.get('container_stopped') is not True
                or not _hex(container.get('container_id'), 64) or not _hex(container.get('operation'), 32)
                or boundary.get('observations_verified') is not True
                or boundary.get('full_isolation_accepted') is not False):
            raise ValueError('Candidate container evidence mismatch')
        containers.append(container['container_id'])
    if len(set(containers)) != 3:
        raise ValueError('Validation, build and import must use distinct containers')
    if imported.get('origin_receipt_sha256') != hashlib.sha256(build_raw).hexdigest():
        raise ValueError('Import is not bound to this build')
    if imported.get('mode') != 'import_check':
        raise ValueError('Explicit import evidence required')
    candidate = _mapping(build.get('candidate'))
    recovered = _mapping(imported.get('candidate'))
    keys = {'commit', 'parent', 'tree', 'manifest_sha256', 'bundle_sha256', 'bundle_bytes',
            'production_accepted', 'published'}
    if (set(candidate) != keys or not _hex(candidate.get('commit'), 40)
            or candidate.get('parent') != expected['base'] or candidate.get('tree') != expected['tree']
            or candidate.get('manifest_sha256') != manifest_sha256
            or candidate.get('production_accepted') is not False or candidate.get('published') is not False
            or not isinstance(bundle, bytes) or not 0 < len(bundle) <= 16*1024*1024
            or type(candidate.get('bundle_bytes')) is not int or candidate['bundle_bytes'] != len(bundle)
            or candidate.get('bundle_sha256') != hashlib.sha256(bundle).hexdigest()
            or not same_json({key: recovered.get(key) for key in keys}, candidate)
            or recovered.get('import_verified') is not True
            or type(recovered.get('verified_file_count')) is not int
            or recovered['verified_file_count'] != expected['file_count']
            or recovered.get('checked_out') is not False or recovered.get('source_executed') is not False):
        raise ValueError('Recovered commit or bundle mismatch')
    return dict(schema=1, commit=candidate['commit'], parent=expected['base'], tree=expected['tree'],
                manifest_sha256=manifest_sha256, bundle_sha256=candidate['bundle_sha256'],
                validation_dispatch_sha256=dispatch_sha, build_receipt_sha256=hashlib.sha256(build_raw).hexdigest(),
                import_receipt_sha256=hashlib.sha256(import_raw).hexdigest(), validator_id=validator_id,
                image_id=image_id, file_count=expected['file_count'],
                test_command_succeeded=True, reported_test_count=test['reported_test_count'],
                candidate_import_verified=True, turn_bound=False, runtime_state_observed=False,
                review_required=True, production_accepted=False, resume_available=False)


def bind_turn_candidate(binding, registration, **evidence):
    """Join a load_turn_binding result and current registration to raw evidence.

Never trust precomputed candidate/validation summaries supplied by a model.
No filesystem writes, live-state claim, STOP removal, or fence release occurs.
"""
    binding = _mapping(binding)
    registration = _mapping(registration)
    roles = _mapping(registration.get('roles'))
    role = binding.get('role')
    if not isinstance(role, str) or role not in ROLES:
        raise ValueError('Known role required')
    registered_role = _mapping(roles.get(role))
    if (registration.get('migration_epoch') != binding.get('migration_epoch')
            or registered_role.get('id') != binding.get('sandbox_id')):
        raise ValueError('Turn is not from the current registered role and epoch')
    validator = bind_result(binding, evidence['dispatch_raw'], evidence['stdout_raw'],
                            validator_id=evidence['validator_id'], image_id=evidence['image_id'])
    if validator['outcome'] != 'test_command_succeeded':
        raise ValueError('Failed turn cannot yield a successful candidate')
    candidate = bind_candidate(**evidence)
    if (candidate['manifest_sha256'] != binding['manifest_sha256']
            or candidate['parent'] != binding['base']):
        raise ValueError('Candidate belongs to another captured turn')
    return dict(candidate, turn_bound=True, turn_binding=dict(binding),
                turn_validation=validator, fence_release_authorized=False)
