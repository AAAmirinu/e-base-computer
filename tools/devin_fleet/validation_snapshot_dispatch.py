"""Trusted outer-VM dispatch; reads inert captured blobs, never source execution."""
import base64
import fcntl
import json
import os
from pathlib import Path
import subprocess
import hashlib
import resource
import uuid
from sandbox_snapshot_receiver import validate_snapshot
from durable import atomic_write_json, _sync_directory
from validation_dispatch_receipt import parse_summary
from validation_pending_gate import unresolved_dispatches
from validation_snapshot_input import _file, load_snapshot, digest_argument, load_capture, load_turn_binding
from validation_dispatch_receipt import _pairs
from turn_validation_result import bind_result, same_json
from snapshot_git_tree import expected_tree

ROOT = Path('/home/fleet/controller-validation/snapshot-evidence-b5bcef2169474269b2bc5b3ecfbde7ff/source-snapshot')
DIGEST = '11ae09248ff91a77e069ff7eaf6921b9247d1a6cc63897399a78fbbc6782febc'
SBX = ['sh', '/home/fleet/sbx-headless.sh']
UUID = '84a0fc99-4cbb-4383-a1df-4c22bbe0d2e6'
IMAGE = 'sha256:1750198e508ceeabc96bb744de28bce36fe877ab0cd7f5a4a2eb0eff6d710f1f'


def limit_logs():
    resource.setrlimit(resource.RLIMIT_FSIZE, (8 * 1024 * 1024, 8 * 1024 * 1024))


def inventory():
    result = subprocess.run(SBX + ['ls', '--json'], capture_output=True, text=True, check=True, timeout=30)
    values = json.loads(result.stdout)['sandboxes']
    target = [v for v in values if v['name'] == 'e-base-validation']
    if len(target) != 1 or target[0]['id'] != UUID:
        raise RuntimeError('Validation VM identity mismatch')
    return values, target[0]


def main(argv=None, *, observer=None, expected_registration=None,
         prepared_trial_registration=None, prepared_trial_check=None,
         prepared_trial_test=False):
    # Deliberately not a general callback: only the fixed inert trial is allowed.
    trial = prepared_trial_registration is not None or prepared_trial_check is not None
    if trial:
        import prepared_candidate_trial_state as trial_state
        if (prepared_trial_check is not trial_state.check_runtime_registration
                or prepared_trial_registration is None
                or expected_registration is not None):
            raise ValueError('Exact prepared trial registration check required')
        prepared_trial_check(prepared_trial_registration)
    if type(prepared_trial_test) is not bool:
        raise TypeError('Prepared trial test selector must be boolean')
    if prepared_trial_test and not trial:
        raise ValueError('Prepared trial test requires exact prepared trial identity')
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', required=True)
    parser.add_argument('--manifest-sha256', type=digest_argument, required=True)
    parser.add_argument('--capture-receipt')
    parser.add_argument('--turn-receipt')
    images = parser.add_mutually_exclusive_group()
    images.add_argument('--git-image-candidate', action='store_true')
    images.add_argument('--registered-git-image', action='store_true')
    args = parser.parse_args(argv)
    if trial and not args.registered_git_image:
        raise ValueError('Prepared trial requires registered Git image dispatch')
    image = IMAGE
    use_git_image = args.git_image_candidate or args.registered_git_image
    if use_git_image:
        image = 'sha256:cee9fe9272c17a34c0b1620485843ff67431dcc18d2e0f7380581fe28f5aeaf4'
        build = json.loads(Path('/home/fleet/controller-validation/git-image-build-edfcfgb7/receipt.json').read_text())
        if (build.get('phase') != 'closed' or build.get('network_denied_after') is not True
                or build.get('all_vms_stopped') is not True or build.get('cleanup_errors') != []
                or build.get('build', {}).get('built') is not True
                or build['build'].get('image_id') != image):
            raise RuntimeError('Closed fixed Git image build required')
        if args.git_image_candidate and (args.turn_receipt or args.capture_receipt):
            raise ValueError('Candidate image is maintenance-only')
        if args.registered_git_image:
            registered = (prepared_trial_registration if trial else
                json.loads(Path('/home/fleet/controller-validation/sandbox-registry.json').read_text()))
            if ((not trial and registered.get('production_enabled') is not True)
                    or registered.get('validation_image_id') != image
                    or not args.turn_receipt or not args.capture_receipt):
                raise ValueError('Registered fixed image and bound production turn required')
    if os.environ.get('WSL_DISTRO_NAME') != 'EBase-Sandboxes' or os.getuid() != 1000:
        raise RuntimeError('Dedicated distro required')
    source_directory = Path(args.snapshot)
    trusted_root = Path('/home/fleet/controller-validation')
    if trusted_root not in source_directory.parents or source_directory.resolve() != source_directory:
        raise ValueError('Snapshot must be under the dedicated controller tree')
    for ancestor in source_directory.parents:
        meta = ancestor.stat()
        if meta.st_uid not in (0, os.getuid()) or meta.st_mode & 0o022:
            raise ValueError('Snapshot ancestor is not protected')
    expected_digest = args.manifest_sha256
    raw, blobs, manifest = load_snapshot(args.snapshot, expected_digest)
    capture_evidence = None
    turn_evidence = None
    registration = None
    if args.turn_receipt and not args.capture_receipt:
        raise ValueError('Turn validation requires an explicit capture receipt')
    if args.capture_receipt:
        registration = (prepared_trial_registration if trial else
            json.loads(_file(trusted_root / 'sandbox-registry.json', 65536), object_pairs_hook=_pairs))
        capture_evidence = load_capture(args.capture_receipt, source_directory, expected_digest, manifest, registration['roles'])
        if args.turn_receipt:
            turn_evidence = load_turn_binding(args.turn_receipt, capture_evidence,
                                               expected_epoch=registration.get('migration_epoch'))
        elif 'operation_id' in capture_evidence['capture']:
            raise ValueError('Model-turn capture requires its explicit turn receipt')
    packet = json.dumps({'manifest': base64.b64encode(raw).decode(),
                         'blobs': {k: base64.b64encode(v).decode() for k, v in blobs.items()}}).encode()
    with open('/tmp/e-base-devin-fleet-global.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if registration is not None or expected_registration is not None or args.registered_git_image:
            current = json.loads(_file(trusted_root / 'sandbox-registry.json', 65536), object_pairs_hook=_pairs)
            if trial:
                prepared_trial_check(prepared_trial_registration)
                if not same_json(registration, prepared_trial_registration):
                    raise ValueError('Prepared trial registration changed before admission')
            elif registration is not None and not same_json(current, registration):
                raise ValueError('Capture registration changed before admission')
            if not trial and expected_registration is not None and not same_json(current, expected_registration):
                raise ValueError('Expected registration changed before admission')
            if not trial and (expected_registration is not None or args.registered_git_image):
                if (current.get('production_enabled') is not True
                        or current.get('validation_image_id') != image):
                    raise ValueError('Production image registration changed before admission')
        values, current_vm = inventory()
        if any(v['status'] != 'stopped' for v in values):
            raise RuntimeError('All VMs must be stopped before admission')
        holds = unresolved_dispatches('/home/fleet/controller-validation', UUID, current_vm)
        if holds:
            print(json.dumps({'admission': 'held', 'unresolved_dispatches': holds}), flush=True)
            raise RuntimeError('Unresolved dispatch evidence; VM execution refused')
        policy = subprocess.run(SBX + ['policy', 'check', 'network', '--sandbox', 'e-base-validation',
            '--json', 'registry-1.docker.io'], capture_output=True, text=True, timeout=30)
        if json.loads(policy.stdout)['allowed'] is not False:
            raise RuntimeError('Validation network denial missing')
        directory = Path('/home/fleet/controller-validation/dispatch-' + uuid.uuid4().hex)
        directory.mkdir(mode=0o700)
        _sync_directory(directory.parent)
        journal = {'schema': 1, 'phase': 'prepared', 'sandbox_id': UUID, 'manifest_sha256': expected_digest,
                   'image_id': image, 'base': manifest['base'], 'validation_passed': False}
        journal['expected_git_tree'] = expected_tree(raw, expected_digest, blobs)
        if capture_evidence is not None:
            journal['capture_evidence'] = capture_evidence
        if turn_evidence is not None:
            journal['turn_evidence'] = turn_evidence
        def save():
            atomic_write_json(directory / 'dispatch.json', journal)
        save()
        try:
            journal['phase'] = 'running'
            save()
            guest_runner = ['python3', '/tmp/validation_source_smoke.py']
            if use_git_image:
                # Execute trusted controller code, not repository source, in the VM.
                # Keep the existing guest runner file and default image untouched.
                runner = (trusted_root / 'validation_source_smoke.py').read_text()
                if len(runner) > 32768:
                    raise ValueError('Oversize trusted runner')
                guest_runner = ['python3', '-I', '-c',
                    "import sys; sys.path.insert(0, '/tmp'); exec(compile(" + repr(runner)
                    + ", '<trusted-validation-runner>', 'exec'))"]
            with (directory / 'stdout.log').open('xb') as stdout, (directory / 'stderr.log').open('xb') as stderr:
                try:
                    result = subprocess.run(SBX + ['exec', '-i', 'e-base-validation', 'timeout', '165',
                        *guest_runner, '--manifest-sha256', expected_digest]
                        + (['--git-image-candidate'] if use_git_image else [])
                        + (['--fixed-prepared-trial-test'] if prepared_trial_test else []),
                        input=packet, timeout=180,
                        stdout=stdout, stderr=stderr, preexec_fn=limit_logs)
                finally:
                    stdout.flush()
                    stderr.flush()
                    os.fsync(stdout.fileno())
                    os.fsync(stderr.fileno())
            journal['returncode'] = result.returncode
            output = (directory / 'stdout.log').read_bytes()
            journal['stdout_sha256'] = hashlib.sha256(output).hexdigest()
            journal['runner_summary'] = parse_summary(output, expected_digest, image, manifest['base'])
            journal['phase'] = 'result_received'
            save()
            if result.returncode:
                raise RuntimeError('Source smoke failed')
        except BaseException as error:
            journal.update(phase='inspection_required', error_type=type(error).__name__)
            save()
            raise
        finally:
            try:
                subprocess.run(SBX + ['stop', 'e-base-validation'], check=True, timeout=30)
                _, target = inventory()
                if target['status'] != 'stopped':
                    raise RuntimeError('Validation VM stop not verified')
                journal['validation_vm_stopped'] = True
                if journal['phase'] == 'result_received':
                    journal['phase'] = 'complete'
                if turn_evidence is not None and 'runner_summary' in journal:
                    try:
                        journal['turn_result'] = bind_result(turn_evidence,
                            json.dumps(journal, sort_keys=True).encode(),
                            (directory / 'stdout.log').read_bytes(), validator_id=UUID, image_id=image)
                    except (ValueError, TypeError, KeyError):
                        journal.update(phase='inspection_required', turn_result_binding='rejected')
                save()
            except BaseException as error:
                journal.update(phase='cleanup_failed', cleanup_error_type=type(error).__name__)
                save()
                raise
            finally:
                if observer is not None:
                    observer(directory)
                print(json.dumps({'dispatch_directory': str(directory), 'phase': journal['phase'],
                                  'validation_vm_stopped': journal.get('validation_vm_stopped', False)}), flush=True)
        if journal.get('turn_result_binding') == 'rejected':
            raise RuntimeError('Turn result binding rejected; inspect without retry')
        return directory


if __name__ == '__main__':
    main()
