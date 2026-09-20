"""Connect guest input/model/checkpoint phases, leaving validation uncommitted.

No production admission implementation or CLI activation is supplied here.
The trusted admission callback must verify free catalog, permission policy,
capacity and host boundaries; raising on any unresolved gate. Offline auth status
is diagnostic, not a prerequisite proof: current model access is established only
by the single model attempt and fresh verified export, with no automatic retry.
Never run generated
tests in the authenticated model VM. The returned snapshot awaits a separate
credential-free validator and transactional candidate commit implementation.
"""
from contextlib import nullcontext
from datetime import datetime, timezone
import math
import os
from pathlib import Path
import time
import uuid

from durable import atomic_write_json, _sync_directory
import fleet
from sandbox_repository import GuestRepository
from sandbox_sync import _migration_epoch
from sandbox_snapshot import capture_source_snapshot, persist_source_snapshot
from sandbox_turn_fence import reserve_turn


def run_guest_model_phase(runtime, root, role, entry, state, settings, run_directory,
                          *, admission, sequence, candidate_patches=None,
                          validation_feedback=None, validation_feedback_sha256=None,
                          network_scope=None, trial_guest_root=None):
    if network_scope is not None and not callable(network_scope):
        raise ValueError('Trusted network scope callback required')
    epoch = _migration_epoch(runtime.registration)
    if runtime.registration.get('production_enabled') is not True:
        raise RuntimeError('Production model admission remains disabled')
    if runtime.registration.get('controller_root') != str(runtime.stop_path.parent):
        raise ValueError('Production turn root must match trusted registration')
    if role not in runtime.registration['roles'] or not callable(admission):
        raise ValueError('Registered role and trusted admission callback required')
    if type(sequence) is not int or sequence < 0:
        raise ValueError('Explicit nonnegative operation sequence required')
    timeout = settings.get('turn_timeout_seconds')
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('Finite positive turn timeout required')
    if state.get('sessions') and state.get('migration_epoch') != epoch:
        raise ValueError('Legacy or foreign session state cannot resume')
    root, directory = Path(root), Path(run_directory)
    if not root.is_absolute() or not directory.is_absolute():
        raise ValueError('Absolute trusted driver paths required')
    started = time.monotonic()
    def remaining():
        if os.path.lexists(runtime.stop_path):
            raise RuntimeError('Fleet STOP blocks model phase')
        seconds = min(timeout - (time.monotonic() - started),
                      (fleet.EXPIRY - datetime.now(timezone.utc)).total_seconds())
        if seconds <= 0:
            raise RuntimeError('Model phase deadline reached; no fallback')
        return seconds
    remaining()
    receipt = {'schema': 1, 'operation_id': uuid.uuid4().hex, 'migration_epoch': epoch,
               'role': role, 'sequence': sequence, 'phase': 'awaiting_admission',
               'sandbox_id': runtime.registration['roles'][role]['id']}
    # Process restart or a new output directory must not bypass a prior turn.
    # Keep this reservation through validation; no automatic permission retry.
    reserve_turn(runtime.stop_path.parent, receipt, directory)
    directory.mkdir(mode=0o700)
    _sync_directory(directory.parent)
    path = directory / 'turn.json'
    atomic_write_json(path, receipt)
    def check_admission(stage, repo=None, prepared=None):
        receipt.update(admission_stage=stage, admission_status='checking')
        atomic_write_json(path, receipt)
        try:
            admission(runtime, role, settings, stage=stage, repo=repo,
                      prepared=prepared, timeout=remaining())
        except BaseException:
            # Preserve the fence and avoid storing possibly sensitive exception text.
            # This is not evidence of VM shutdown or permission to retry.
            receipt.update(phase='held', admission_status='incomplete',
                           reason='Admission did not complete; inspection required')
            atomic_write_json(path, receipt)
            raise
        receipt['admission_status'] = 'passed'
        if stage == 'initial':
            receipt['phase'] = 'admitted'
        atomic_write_json(path, receipt)
    check_admission('initial')
    remaining()
    with runtime.role(role) as repo:
        if not isinstance(repo, GuestRepository):
            raise TypeError('Guest repository required; no host fallback')
        repo.restrict_git_to_model_reads()
        check_admission('before_prepare', repo=repo)
        remaining()
        prepared = fleet.prepare_guest_turn(root, repo, role, entry, state,
                    session=state.get('sessions', {}).get(role), candidate_patches=candidate_patches,
                    validation_feedback=validation_feedback,
                    validation_feedback_sha256=validation_feedback_sha256,
                    trial_guest_root=trial_guest_root)
        receipt.update(phase='prepared', base=prepared['base'],
                       config_sha256=prepared['config_sha256'], prompt_sha256=prepared['prompt_sha256'],
                       validation_feedback_sha256=prepared.get('validation_feedback_sha256'),
                       extra_files_sha256=prepared['extra_files_sha256'])
        atomic_write_json(path, receipt)
        remaining()
        # No default permission mutation. A closed policy without an explicit
        # lifecycle scope is rejected by production network admission.
        window=(network_scope(runtime,role,repo,directory/'network-window',timeout=remaining())
                if network_scope is not None else nullcontext())
        with window:
            check_admission('before_model', repo=repo, prepared=prepared)
            proc, export = fleet.execute_model_attempt(repo, prepared['args'], directory / 'model.log',
                runtime.stop_path, remaining(), directory / 'model-operation.json', role, 0,
                expected_config_sha256=prepared['config_sha256'], migration_epoch=epoch,
                sequence=sequence, expected_prompt_sha256=prepared['prompt_sha256'],
                expected_extra_files_sha256=prepared['extra_files_sha256'])
    # Export verification alone does not prove descendants stopped. Lease exit does.
    receipt.update(phase='model_stopped', returncode=proc.returncode)
    atomic_write_json(path, receipt)
    if proc.returncode != 0:
        receipt.update(phase='held', reason='Model attempt failed; no automatic permission retry')
        atomic_write_json(path, receipt)
        return receipt
    fleet.check_model(export)
    session = export.get('session_id')
    if not isinstance(session, str) or not session.strip():
        raise RuntimeError('Verified session identity missing')
    remaining()
    receipt.update(phase='inspection_pending')
    atomic_write_json(path, receipt)
    with runtime.role(role) as repo:
        if not isinstance(repo, GuestRepository):
            raise TypeError('Guest repository required; no host fallback')
        repo.restrict_git_to_model_reads()
        check_admission('before_inspection', repo=repo)
        remaining()
        report = fleet.read_repository_json(repo, '.fleet/report.json', {})
        if not isinstance(report.get('summary'), str) or not report['summary'].strip():
            raise RuntimeError('Model checkpoint summary missing')
        if fleet.sha(repo) != prepared['base']:
            raise RuntimeError('Model changed Git HEAD')
        changed = fleet.changes(repo)
        fleet.check_owned_changes(repo, changed, entry['paths'], role)
        snapshot = {'base': prepared['base'], 'changed': changed,
                    'fingerprints': fleet.fingerprints(repo, changed)}
        source_snapshot = capture_source_snapshot(repo, snapshot)
        # The quiescence checkpoint above intentionally includes controller
        # metadata. Validation receipts bind source-only paths, matching the
        # source snapshot contract that excludes .fleet/**.
        source_changed=[path for path in changed
                        if path!='.fleet' and not path.startswith('.fleet/')]
        snapshot={'base':snapshot['base'],'changed':source_changed,
                  'fingerprints':{path:snapshot['fingerprints'][path]
                                  for path in source_changed}}
        decision = fleet.read_repository_json(repo, '.fleet/decision.json', {}) if role == 'coordinator' else {}
    receipt.update(phase='inspection_stopped')
    atomic_write_json(path, receipt)
    remaining()
    persist_source_snapshot(directory / 'source-snapshot', source_snapshot)
    snapshot['manifest_sha256'] = source_snapshot['manifest_sha256']
    files = source_snapshot['manifest']['files']
    atomic_write_json(directory / 'capture.json', {
        'schema': 1, 'role': role, 'sandbox_id': receipt['sandbox_id'],
        'operation_id': receipt['operation_id'], 'migration_epoch': epoch,
        'sequence': sequence, 'base': snapshot['base'],
        'manifest_sha256': source_snapshot['manifest_sha256'],
        'snapshot_directory': str(directory / 'source-snapshot'),
        'source_checkpoint': snapshot, 'source_executed': False,
        'source_vm_stopped': True, 'file_count': len(files),
        'source_bytes': sum(f['size'] for f in files),
        'blob_count': len({f['sha256'] for f in files}),
    })
    # Report/model assertions are untrusted evidence, never validation acceptance.
    atomic_write_json(directory / 'checkpoint.json', {'report': report, 'decision': decision,
                                                     'snapshot': snapshot})
    receipt.update(phase='awaiting_validation', session_id=session, snapshot=snapshot,
                   validation_passed=False, committed=False)
    atomic_write_json(path, receipt)
    return receipt
