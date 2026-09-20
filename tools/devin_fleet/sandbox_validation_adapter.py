"""Actual single-turn validation adapter. No model or fallback execution."""
import json
from pathlib import Path
import re

from managed_cli_guard import require_managed_namespace
import validation_snapshot_dispatch as dispatcher
from validation_snapshot_input import _file, load_snapshot, load_capture, load_turn_binding
from validation_dispatch_receipt import _pairs
from turn_validation_result import bind_result, same_json

ROOT = Path('/home/fleet/controller-validation')
GIT_IMAGE = 'sha256:cee9fe9272c17a34c0b1620485843ff67431dcc18d2e0f7380581fe28f5aeaf4'


def validate(snapshot_directory, capture_path, turn_path, registration):
    """Run after model runtime exit. Existing dispatcher owns global lock + VM.

Failures without complete, bound shutdown evidence propagate; never retry.
Consistent test failures return their raw evidence for the cycle to archive.
"""
    require_managed_namespace()
    disk = json.loads(_file(ROOT/'sandbox-registry.json', 65536), object_pairs_hook=_pairs)
    if not same_json(disk, registration) or disk.get('production_enabled') is not True:
        raise ValueError('Unchanged production registration required')
    image = registration.get('validation_image_id')
    if image not in (dispatcher.IMAGE, GIT_IMAGE):
        raise ValueError('Explicit supported pinned validation image required')
    snapshot = Path(snapshot_directory)
    if ROOT not in snapshot.parents or snapshot.resolve() != snapshot:
        raise ValueError('Dedicated protected snapshot path required')
    turn = json.loads(_file(Path(turn_path), 65536), object_pairs_hook=_pairs)
    digest = turn.get('snapshot', {}).get('manifest_sha256')
    _, _, manifest = load_snapshot(snapshot, digest)
    capture = load_capture(capture_path, snapshot, digest, manifest, registration['roles'])
    binding = load_turn_binding(turn_path, capture, expected_epoch=registration.get('migration_epoch'))
    arguments = ['--snapshot', str(snapshot), '--manifest-sha256', digest,
                 '--capture-receipt', str(capture_path), '--turn-receipt', str(turn_path)]
    if image == GIT_IMAGE:
        arguments.append('--registered-git-image')
    observed = []
    failure = None
    try:
        dispatcher.main(arguments, observer=observed.append, expected_registration=registration)
    except Exception as error:
        failure = error
    if len(observed) != 1:
        raise RuntimeError('No unique completed dispatch; inspect without retry') from failure
    directory = Path(observed[0])
    if (directory.parent != ROOT or directory.resolve() != directory
            or re.fullmatch('dispatch-[0-9a-f]{32}', directory.name) is None):
        raise ValueError('Unexpected dispatch evidence directory')
    raw = _file(directory/'dispatch.json', 8*1024*1024)
    stdout = _file(directory/'stdout.log', 8*1024*1024)
    result = bind_result(binding, raw, stdout, validator_id=dispatcher.UUID, image_id=image)
    if failure is not None and result['outcome'] != 'test_command_failed':
        raise RuntimeError('Dispatch exception contradicts result; inspect without retry') from failure
    return dict(dispatch_raw=raw, stdout_raw=stdout, validator_id=dispatcher.UUID, image_id=image)
