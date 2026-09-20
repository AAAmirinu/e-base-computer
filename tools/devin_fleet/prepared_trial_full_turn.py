"""Read-only verifier for the single successful prepared v12 full turn."""
import json
from pathlib import Path
import re

from candidate_review_store import inspect_candidate
import production_registration_prepare
from turn_validation_result import same_json
from validation_dispatch_receipt import _pairs
from validation_snapshot_input import _file

CYCLE_NAME = 'fixed-inert-one-turn-v12'
ROOT = production_registration_prepare.ROOT
TRIAL_RUN = ROOT / 'production-registration-trial-v11'
STATE = TRIAL_RUN / 'state'
CONTROLLER = TRIAL_RUN / 'controller'


def _json(path, limit=1048576):
    return json.loads(_file(path, limit), object_pairs_hook=_pairs)


def inspect():
    prepared = production_registration_prepare.inspect()
    registration = _json(STATE / 'registration.json')
    binding = _json(STATE / 'binding.json')
    commit = _json(STATE / 'commit.json')
    status = _json(STATE / 'status.json')
    source = _json(STATE / 'source-registry.json')
    active = _json(ROOT / 'sandbox-registry.json')
    if (registration.get('controller_root') != str(CONTROLLER)
            or registration.get('migration_epoch') != prepared['migration_epoch']
            or binding.get('candidate_sha256') != prepared['candidate_sha256']
            or binding.get('migration_epoch') != prepared['migration_epoch']
            or commit.get('candidate_sha256') != prepared['candidate_sha256']
            or commit.get('migration_epoch') != prepared['migration_epoch']
            or not same_json(source, active)
            or active.get('production_enabled') is not False
            or any(record.get(key) is not False for record in (binding, commit, status)
                   for key in ('activated', 'published', 'automatic_resume', 'retry'))):
        raise ValueError('Archived prepared trial identity mismatch')
    cycle_path = CONTROLLER / 'cycles' / CYCLE_NAME / 'cycle.json'
    cycle = _json(cycle_path, 65536)
    operation = cycle.get('operation_id')
    expected_record = CONTROLLER / 'candidate-review' / str(operation) / 'candidate.json'
    if (cycle.get('schema') != 1 or cycle.get('phase') != 'pending_review'
            or cycle.get('role') != 'machine' or cycle.get('sequence') != 0
            or not isinstance(operation, str) or re.fullmatch('[0-9a-f]{32}', operation) is None
            or cycle.get('candidate_record') != str(expected_record)
            or cycle.get('model_retry_allowed') is not False
            or cycle.get('resume_available') is not False
            or cycle.get('published') is not False):
        raise ValueError('Exact successful prepared trial cycle required')
    candidate = inspect_candidate(CONTROLLER, registration, operation)
    evidence = candidate['evidence']
    validation = evidence.get('turn_validation', {})
    binding = evidence.get('turn_binding', {})
    candidate_archive = cycle.get('candidate_archive', {})
    validation_archive = cycle.get('validation_archive', {})
    if (candidate.get('archive_verified') is not True
            or candidate.get('phase') != 'pending_review'
            or any(candidate.get(key) is not False for key in
                   ('published', 'merged', 'fence_released', 'resume_available'))
            or evidence.get('turn_bound') is not True
            or evidence.get('candidate_import_verified') is not True
            or evidence.get('production_accepted') is not False
            or evidence.get('review_required') is not True
            or evidence.get('test_command_succeeded') is not True
            or evidence.get('reported_test_count') != 1
            or validation.get('outcome') != 'test_command_succeeded'
            or validation.get('production_accepted') is not False
            or validation.get('review_required') is not True
            or validation.get('reported_test_count') != 1
            or validation.get('committed') is not False
            or binding.get('operation_id') != operation
            or binding.get('migration_epoch') != prepared['migration_epoch']
            or candidate_archive != {'build.json': evidence.get('build_receipt_sha256'),
                'candidate.bundle': evidence.get('bundle_sha256'),
                'import.json': evidence.get('import_receipt_sha256')}
            or validation_archive != {'dispatch.json': evidence.get('validation_dispatch_sha256'),
                'stdout.log': validation.get('stdout_sha256')}):
        raise ValueError('Prepared full-turn evidence binding mismatch')
    return {'verified': True, 'cycle': CYCLE_NAME, 'operation_id': operation,
        'candidate_sha256': prepared['candidate_sha256'],
        'migration_epoch': prepared['migration_epoch'], 'role': 'machine',
        'reported_test_count': 1, 'candidate_import_verified': True,
        'candidate_pending_review': True, 'activated': False, 'published': False}
