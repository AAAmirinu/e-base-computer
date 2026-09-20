"""Recheck live controller registration and the exact unresolved candidate turn.

The returned check belongs inside the common runtime lock. It grants no network
access, clears no fence and never accepts a candidate or resumes a model.
"""
import json
import os
from pathlib import Path

from sandbox_turn_fence import ROLES, _directory, _reservation
from validation_snapshot_input import _file, load_snapshot, load_capture, load_turn_binding
from validation_dispatch_receipt import _pairs
from turn_validation_result import same_json

ROOT = Path('/home/fleet/controller-validation')
IMAGE = 'sha256:cee9fe9272c17a34c0b1620485843ff67431dcc18d2e0f7380581fe28f5aeaf4'


def make_admission(registration, binding, *, registration_check=None):
    if registration_check is not None:
        from prepared_candidate_trial_state import check_runtime_registration
        if registration_check is not check_runtime_registration:
            raise ValueError('Only the fixed prepared-candidate trial checker is allowed')
    # Freeze expectations: later caller mutations must not redefine admission.
    registration = json.loads(json.dumps(registration, allow_nan=False))
    binding = json.loads(json.dumps(binding, allow_nan=False))
    if (not isinstance(registration, dict) or not isinstance(binding, dict)
            or (registration_check is not None and not callable(registration_check))):
        raise ValueError('Explicit controller registration and turn required')
    role = binding.get('role')
    root_value = registration.get('controller_root')
    if not isinstance(root_value, str):
        raise ValueError('Registered controller root required')
    root = Path(root_value)
    if (not root.is_absolute() or root.resolve() != root or ROOT not in root.parents
            or registration.get('production_enabled') is not True
            or registration.get('validation_image_id') != IMAGE
            or not isinstance(role, str) or role not in ROLES
            or not isinstance(registration.get('roles'), dict)
            or not isinstance(registration['roles'].get(role), dict)
            or registration['roles'][role].get('id') != binding.get('sandbox_id')
            or registration.get('migration_epoch') != binding.get('migration_epoch')):
        raise ValueError('Current explicit production turn registration required')
    frozen_fence = None

    def check():
        nonlocal frozen_fence
        for parent in root.parents:
            _directory(parent)
        _directory(ROOT, private=True)
        _directory(root, private=True)
        if os.path.lexists(root/'STOP'):
            raise RuntimeError('STOP blocks candidate execution')
        if registration_check is None:
            current = json.loads(_file(ROOT/'sandbox-registry.json', 65536), object_pairs_hook=_pairs)
            if not same_json(current, registration):
                raise ValueError('Candidate registration changed')
        elif registration_check(registration) is not None:
            raise ValueError('Trial registration checker must return no value')
        fences = root/'model-turn-fences'
        _directory(fences, private=True)
        fence_raw = _file(fences/(role+'.json'), 65536)
        reservation = _reservation(fence_raw, role)
        for key in ('operation_id', 'migration_epoch', 'role', 'sequence', 'sandbox_id'):
            if not same_json(reservation[key], binding.get(key)):
                raise ValueError('Candidate does not match unresolved turn')
        if frozen_fence is not None and fence_raw != frozen_fence:
            raise ValueError('Candidate reservation changed')
        run = Path(reservation['run_directory'])
        if root not in run.parents or run.resolve() != run:
            raise ValueError('Turn directory must remain under registered root')
        for parent in run.parents:
            _directory(parent)
        _directory(run, private=True)
        snapshot = run/'source-snapshot'
        _, _, manifest = load_snapshot(snapshot, binding.get('manifest_sha256'))
        capture = load_capture(run/'capture.json', snapshot, binding.get('manifest_sha256'),
                               manifest, registration['roles'])
        observed = load_turn_binding(run/'turn.json', capture,
                                     expected_epoch=registration['migration_epoch'])
        if not same_json(observed, binding):
            raise ValueError('Candidate turn evidence changed')
        # Freeze only after the complete on-disk check succeeds.
        frozen_fence = fence_raw

    check()
    return check
