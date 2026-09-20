"""One dedicated-VM turn pipeline. No scheduler, automatic retry, or publication.

Trusted deployment must provide admission and separate-validator adapters.
There are no permissive defaults: missing adapters are rejected before a model.
"""
import hashlib
import os
from pathlib import Path

from durable import atomic_write_json, _sync_directory, _atomic_bytes
from sandbox_turn import run_guest_model_phase
from validation_snapshot_input import load_snapshot, load_capture, load_turn_binding
from turn_validation_result import bind_result, same_json
from candidate_review_store import record_candidate
from sandbox_turn_fence import _directory


def run_registered_one_turn(*, registration, controller_root, project_root, role,
                            entry, state, settings, cycle_directory, sequence,
                            runtime_factory, validate, build_and_import):
    """Production binding with fixed live guards; no caller-supplied bypass.

This is a library entry, not authorization to create production registration.
It retains the raw validation/candidate adapters and the existing held journal.
"""
    from registered_turn_guards import make_registered_turn_guards
    guards = make_registered_turn_guards(registration, role, entry, settings)
    return run_one_turn(registration=registration, controller_root=controller_root,
        project_root=project_root, role=role, entry=entry, state=state, settings=settings,
        cycle_directory=cycle_directory, sequence=sequence, runtime_factory=runtime_factory,
        validate=validate, build_and_import=build_and_import, **guards)


def _archive(parent, name, values):
    for data in values.values():
        if not isinstance(data, bytes) or not 0 < len(data) <= 16*1024*1024:
            raise ValueError('Bounded raw stage evidence required')
    work = parent/name
    work.mkdir(mode=0o700)
    _sync_directory(parent)
    for filename, data in values.items():
        _atomic_bytes(work/filename, data)
    return {filename: hashlib.sha256(data).hexdigest() for filename, data in values.items()}


def run_one_turn(*, registration, controller_root, project_root, role, entry, state, settings,
                 cycle_directory, sequence, runtime_factory, admission, validate, build_and_import,
                 network_scope=None, trial_guest_root=None):
    """Adapters return raw controller-owned bytes, never success booleans.

validate(snapshot_directory, capture_path, turn_path, registration) returns
dispatch_raw/stdout_raw/validator_id/image_id. build_and_import(binding, evidence)
returns build_raw/import_raw/bundle. Both own their isolated lifetimes and stops.
The runtime factory must use the common global lock; its lease closes before
either adapter is called, avoiding nested validator acquisition of that lock.
"""
    if not all(callable(item) for item in (runtime_factory, admission, validate, build_and_import)):
        raise ValueError('Complete trusted adapters required before model admission')
    if network_scope is not None and not callable(network_scope):
        raise ValueError('Trusted network scope callback required')
    root, project, directory = map(Path, (controller_root, project_root, cycle_directory))
    if (registration.get('production_enabled') is not True
            or registration.get('controller_root') != str(root)
            or not all(p.is_absolute() and p.resolve() == p for p in (root, project, directory))
            or root not in directory.parents or role not in registration.get('roles', {})
            or type(sequence) is not int or sequence < 0):
        raise ValueError('Explicit registered production turn required')
    _directory(root, private=True)
    def stop_check():
        if os.path.lexists(root/'STOP'):
            raise RuntimeError('STOP blocks the next turn stage')
    stop_check()
    directory.mkdir(mode=0o700)
    _sync_directory(directory.parent)
    journal = dict(schema=1, phase='prepared', role=role, sequence=sequence,
                   model_retry_allowed=False, resume_available=False, published=False)
    def save(phase):
        journal['phase'] = phase
        atomic_write_json(directory/'cycle.json', journal)
    save('prepared')
    model_directory = directory/'model'
    try:
        save('model_pending')
        with runtime_factory() as runtime:
            if not same_json(runtime.registration, registration) or runtime.stop_path.parent != root:
                raise ValueError('Runtime registration or root changed')
            network_args={'network_scope':network_scope} if network_scope is not None else {}
            model = run_guest_model_phase(runtime, project, role, entry, state, settings,
                model_directory, admission=admission, sequence=sequence,
                trial_guest_root=trial_guest_root, **network_args)
        if model.get('phase') != 'awaiting_validation':
            raise RuntimeError('Model phase did not produce a stopped snapshot')
        journal['operation_id'] = model['operation_id']
        save('awaiting_validation')
        stop_check()
        snapshot = model_directory/'source-snapshot'
        digest = model['snapshot']['manifest_sha256']
        raw, blobs, manifest = load_snapshot(snapshot, digest)
        capture_path, turn_path = model_directory/'capture.json', model_directory/'turn.json'
        capture = load_capture(capture_path, snapshot, digest, manifest, registration['roles'])
        binding = load_turn_binding(turn_path, capture, expected_epoch=registration['migration_epoch'])
        save('validation_running')
        validated = validate(snapshot, capture_path, turn_path, registration)
        if not isinstance(validated, dict) or set(validated) != {'dispatch_raw','stdout_raw','validator_id','image_id'}:
            raise ValueError('Raw validator evidence required')
        journal['validation_archive'] = _archive(directory, 'validation-result',
            {'dispatch.json': validated['dispatch_raw'], 'stdout.log': validated['stdout_raw']})
        save('validation_recorded')
        result = bind_result(binding, **validated)
        if result['outcome'] != 'test_command_succeeded':
            raise RuntimeError('Validation did not succeed; preserve turn for review')
        save('candidate_pending')
        stop_check()
        evidence = dict(validated, manifest_raw=raw, manifest_sha256=digest, blobs=blobs)
        built = build_and_import(binding, dict(evidence))
        if not isinstance(built, dict) or set(built) != {'build_raw','import_raw','bundle'}:
            raise ValueError('Raw candidate build/import evidence required')
        journal['candidate_archive'] = _archive(directory, 'candidate-result',
            {'build.json': built['build_raw'], 'import.json': built['import_raw'], 'candidate.bundle': built['bundle']})
        evidence.update(built)
        save('review_store_pending')
        stop_check()
        with runtime_factory() as runtime:
            if not same_json(runtime.registration, registration) or runtime.stop_path.parent != root:
                raise ValueError('Runtime registration changed before candidate storage')
            path = record_candidate(root, registration, binding, **evidence)
        journal['candidate_record'] = str(path)
        save('pending_review')
        return journal
    except BaseException as error:
        journal.update(interrupted_phase=journal['phase'], error_type=type(error).__name__)
        save('held')
        raise
