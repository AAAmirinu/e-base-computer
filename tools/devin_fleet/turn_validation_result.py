"""Associate trusted validator output with a turn; never accept or resume it."""
import hashlib
import json
import re
import uuid

from validation_dispatch_receipt import _pairs, parse_summary


def same_json(left, right):
    # Python equality treats True, 1 and 1.0 as equal; receipt identity must not.
    options = dict(sort_keys=True, separators=(',', ':'), allow_nan=False)
    return json.dumps(left, **options) == json.dumps(right, **options)


def bind_result(binding, dispatch_raw, stdout_raw, *, validator_id, image_id):
    """Return bounded evidence for review, not a commit or fence-release permit.

    binding must come from load_turn_binding with the current registered epoch.
    The caller supplies controller-owned dispatch/output bytes, not model reports.
    """
    keys = {'turn_sha256', 'capture_sha256', 'operation_id', 'migration_epoch',
            'sequence', 'role', 'sandbox_id', 'manifest_sha256', 'base'}
    if not isinstance(binding, dict) or set(binding) != keys:
        raise ValueError('Explicit verified turn binding required')
    for key in ('turn_sha256', 'capture_sha256', 'manifest_sha256'):
        if not isinstance(binding[key], str) or re.fullmatch('[0-9a-f]{64}', binding[key]) is None:
            raise ValueError('Invalid turn digest')
    if (not isinstance(binding['operation_id'], str)
            or re.fullmatch('[0-9a-f]{32}', binding['operation_id']) is None
            or not isinstance(binding['base'], str) or re.fullmatch('[0-9a-f]{40}', binding['base']) is None
            or type(binding['sequence']) is not int or binding['sequence'] < 0):
        raise ValueError('Invalid bound operation')
    for value in (binding['migration_epoch'], binding['sandbox_id'], validator_id):
        if not isinstance(value, str) or str(uuid.UUID(value)) != value:
            raise ValueError('Canonical VM and epoch identities required')
    if validator_id == binding['sandbox_id']:
        raise ValueError('Validator must be separate from authenticated model VM')
    if not isinstance(image_id, str) or re.fullmatch('sha256:[0-9a-f]{64}', image_id) is None:
        raise ValueError('Pinned validation image required')
    if not isinstance(dispatch_raw, bytes) or len(dispatch_raw) > 8 * 1024 * 1024:
        raise ValueError('Invalid dispatch bytes')
    if not isinstance(stdout_raw, bytes) or len(stdout_raw) > 8 * 1024 * 1024:
        raise ValueError('Invalid validator output')
    dispatch = json.loads(dispatch_raw, object_pairs_hook=_pairs)
    if (not isinstance(dispatch, dict) or type(dispatch.get('schema')) is not int or dispatch['schema'] != 1
            or not same_json(dispatch.get('turn_evidence'), binding)
            or dispatch.get('sandbox_id') != validator_id or dispatch.get('image_id') != image_id
            or dispatch.get('manifest_sha256') != binding['manifest_sha256']
            or dispatch.get('base') != binding['base']
            or dispatch.get('validation_vm_stopped') is not True
            or dispatch.get('validation_passed') is not False
            or dispatch.get('stdout_sha256') != hashlib.sha256(stdout_raw).hexdigest()):
        raise ValueError('Dispatch identity, output or shutdown mismatch')
    envelope = parse_summary(stdout_raw, binding['manifest_sha256'], image_id, binding['base'])
    if not same_json(dispatch.get('runner_summary'), envelope):
        raise ValueError('Saved summary differs from actual output')
    receipt = envelope['receipt']
    boundary = receipt.get('boundary')
    test = receipt.get('test')
    if (not isinstance(boundary, dict) or boundary.get('observations_verified') is not True
            or boundary.get('full_isolation_accepted') is not False
            or not isinstance(test, dict) or test.get('reason') != 'exited'
            or type(test.get('returncode')) is not int
            or type(test.get('reported_test_count')) is not int or test['reported_test_count'] <= 0
            or type(dispatch.get('returncode')) is not int
            or not isinstance(test.get('output_sha256'), str)
            or re.fullmatch('[0-9a-f]{64}', test['output_sha256']) is None):
        raise ValueError('Incomplete execution or boundary evidence')
    success = (test['returncode'] == 0 and receipt.get('test_command_succeeded') is True
               and dispatch['returncode'] == 0 and dispatch.get('phase') == 'complete')
    failure = (test['returncode'] != 0 and receipt.get('test_command_succeeded') is False
               and dispatch['returncode'] != 0 and dispatch.get('phase') == 'inspection_required')
    if not (success or failure):
        raise ValueError('Inconsistent test result; inspect without retry')
    return dict(schema=1, turn_binding=dict(binding),
                outcome='test_command_succeeded' if success else 'test_command_failed',
                # Exclude our derived field so re-reading the final journal is stable.
                dispatch_evidence_sha256=hashlib.sha256(json.dumps(
                    {k: v for k, v in dispatch.items() if k != 'turn_result'},
                    sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
                stdout_sha256=dispatch['stdout_sha256'], test_output_sha256=test['output_sha256'],
                validator_id=validator_id, image_id=image_id,
                reported_test_count=test['reported_test_count'], review_required=True,
                production_accepted=False, committed=False, resume_available=False)
