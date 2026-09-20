"""Run exactly one inert prepared-candidate turn and leave it pending review.

There is no activation, publication, retry, resume, or repository seeding API.
"""
from functools import partial
import json

from sandbox_candidate_adapter import build_and_import
from sandbox_one_turn import run_one_turn
from prepared_candidate_trial_runtime import PreparedCandidateTrialRuntime
from validation_snapshot_input import _file
import prepared_candidate_trial_admission as trial_candidate_admission
import prepared_candidate_trial_guards as trial_guards
import prepared_candidate_trial_state as trial_state
import prepared_trial_project as trial_project
import prepared_trial_validation_adapter as trial_validation
from turn_validation_result import same_json


CYCLE_NAME = 'fixed-inert-one-turn-v12'


def _require_seed_receipt(project):
    """Bind execution to the exact completed seed for this trial generation."""
    raw = _file(trial_state.CONTROLLER / 'seed-v12' / 'receipt.json', 65536)
    value = json.loads(raw)
    expected = {'schema': 1, 'phase': 'complete', 'role': 'machine',
        'retry': False, 'resume_available': False, 'activated': False,
        'published': False, 'bundle_sha256': project['bundle_sha256'],
        'head': project['head'], 'tree': project['tree'],
        'all_vms_stopped': True}
    if type(value) is not dict or not same_json(value, expected):
        raise ValueError('Exact completed trial seed receipt required')
    return value


def preflight():
    """Read-only guest-parent check; creates no cycle and opens no network."""
    registration = trial_state.runtime_registration()
    project = trial_project.inspect()
    _require_seed_receipt(project)
    if registration.get('production_enabled') is not True:
        raise ValueError('Inert prepared-candidate trial registration required')
    with PreparedCandidateTrialRuntime(registration, trial_state.CONTROLLER, capacity=1) as runtime:
        with runtime.role('machine') as repo:
            repo.restrict_git_to_model_reads()
            trial_guards._verify_guest_parent(repo, project)
    return {'preflight': 'passed', 'role': 'machine',
            'head': project['head'], 'tree': project['tree'],
            'network_opened': False, 'cycle_created': False}


def run():
    """Execute the fixed one-shot trial; an existing cycle fails closed."""
    registration = trial_state.runtime_registration()
    project = trial_project.inspect()
    _require_seed_receipt(project)
    request = project['task_request']
    if (registration.get('production_enabled') is not True
            or project.get('production_admitted') is not False
            or project.get('activated') is not False
            or project.get('model_executed') is not False
            or not same_json(request, trial_project.TASK_REQUEST)):
        raise ValueError('Inert prepared-candidate trial binding required')
    role = 'machine'
    entry, state, settings = (request['entry'], request['state'],
                              request['settings'])
    guards = trial_guards.make_guards(registration, role, entry, settings)
    parent_bundle = _file(trial_project.BUNDLE, 16 * 1024 * 1024)
    runtime_factory = partial(PreparedCandidateTrialRuntime, registration,
                              trial_state.CONTROLLER, capacity=1)
    candidate = partial(build_and_import, registration=registration,
        parent_bundle=parent_bundle,
        parent_bundle_sha256=project['bundle_sha256'],
        parent_ref=project['parent_ref'],
        admission_factory=trial_candidate_admission.make_admission)
    return run_one_turn(registration=registration,
        controller_root=trial_state.CONTROLLER,
        project_root=trial_project.PROJECT, role=role, entry=entry,
        state=state, settings=settings,
        cycle_directory=trial_state.CONTROLLER/'cycles'/CYCLE_NAME,
        sequence=0, runtime_factory=runtime_factory,
        validate=trial_validation.validate, build_and_import=candidate,
        trial_guest_root=trial_state.trial_guest_root(),
        **guards)
