"""Validation adapter for the single inert prepared-candidate trial only."""
import json
from pathlib import Path
import re

from managed_cli_guard import require_managed_namespace
import prepared_candidate_trial_state as trial_state
import validation_snapshot_dispatch as dispatcher
from validation_snapshot_input import _file, load_snapshot, load_capture, load_turn_binding
from validation_dispatch_receipt import _pairs
from turn_validation_result import bind_result, same_json

EVIDENCE_ROOT = Path('/home/fleet/controller-validation')
GIT_IMAGE = 'sha256:cee9fe9272c17a34c0b1620485843ff67431dcc18d2e0f7380581fe28f5aeaf4'


def validate(snapshot_directory, capture_path, turn_path, registration):
    """Validate one bound trial turn; never activates, publishes, or retries it."""
    require_managed_namespace()
    trial_state.check_runtime_registration(registration)
    frozen = trial_state.runtime_registration()
    if not same_json(frozen, registration):
        raise ValueError('Exact prepared trial registration required')
    if registration.get('validation_image_id') != GIT_IMAGE:
        raise ValueError('Prepared trial requires the fixed Git validation image')
    snapshot = Path(snapshot_directory)
    controller = trial_state.CONTROLLER
    if controller not in snapshot.parents or snapshot.resolve() != snapshot:
        raise ValueError('Prepared trial snapshot path required')
    turn = json.loads(_file(Path(turn_path), 65536), object_pairs_hook=_pairs)
    digest = turn.get('snapshot', {}).get('manifest_sha256')
    _, _, manifest = load_snapshot(snapshot, digest)
    capture = load_capture(capture_path, snapshot, digest, manifest, registration['roles'])
    binding = load_turn_binding(turn_path, capture,
                                expected_epoch=registration.get('migration_epoch'))
    arguments = ['--snapshot', str(snapshot), '--manifest-sha256', digest,
                 '--capture-receipt', str(capture_path), '--turn-receipt', str(turn_path),
                 '--registered-git-image']
    observed = []
    failure = None
    try:
        dispatcher.main(arguments, observer=observed.append,
            prepared_trial_registration=registration,
            prepared_trial_check=trial_state.check_runtime_registration,
            prepared_trial_test=True)
    except Exception as error:
        failure = error
    if len(observed) != 1:
        raise RuntimeError('No unique completed dispatch; inspect without retry') from failure
    directory = Path(observed[0])
    if (directory.parent != EVIDENCE_ROOT or directory.resolve() != directory
            or re.fullmatch('dispatch-[0-9a-f]{32}', directory.name) is None):
        raise ValueError('Unexpected dispatch evidence directory')
    raw = _file(directory / 'dispatch.json', 8 * 1024 * 1024)
    stdout = _file(directory / 'stdout.log', 8 * 1024 * 1024)
    result = bind_result(binding, raw, stdout, validator_id=dispatcher.UUID,
                         image_id=GIT_IMAGE)
    if failure is not None and result['outcome'] != 'test_command_failed':
        raise RuntimeError('Dispatch exception contradicts result; inspect without retry') from failure
    return dict(dispatch_raw=raw, stdout_raw=stdout, validator_id=dispatcher.UUID,
                image_id=GIT_IMAGE)
