"""Exact non-accepting resolution for one preserved validation-harness failure."""
import hashlib
import json
import os
from pathlib import Path

from managed_cli_guard import require_managed_namespace
from process_control import global_lock_held
from validation_dispatch_receipt import _pairs
from validation_feedback_store import persist_feedback
from validation_snapshot_input import _file

ROOT = Path('/home/fleet/controller-validation')
UUID = '84a0fc99-4cbb-4383-a1df-4c22bbe0d2e6'
DISPATCH_ID = 'ec27229024ab45b9a8be656795d8cac9'
DISPATCH_SHA256 = '34ce8ba3f047247d0c02a5eb86919c8d359318ba4d53b3e3165cc8f1a3002cdf'
STDOUT_SHA256 = 'dd64eaa20121ae206bbb575eb9e7f54d6213546d441f2c3472156b12504bccd9'
TEST_OUTPUT_SHA256 = '66473c1ba197e6ad99b861d98ad23c40a8902f85e4b59dbe36c6ed59b723ac4e'
MANIFEST_SHA256 = 'ac0a21e9fff1af8e54a598c3a73a405c11e68e7f5d1a02ea054280f0fc349554'
REPAIRS = {
    'validation_source_smoke.py': 'ec9f28a1a662a17569d24878c5569842e25e38845cbdf06f4496a55065d6a4bb',
    'validation_snapshot_dispatch.py': '05335666955d46f50a13f5a371684487cef50429b63b8418e57ce9703a478947',
    'prepared_trial_validation_adapter.py': '16c572ea161a957bcd824d6a48890f4d09a991c7d3ea7649d5880ddeeafedb59',
}


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'),
                       allow_nan=False) + '\n').encode()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def build_resolution(dispatch_raw, stdout_raw, repair_sources):
    if (_sha(dispatch_raw) != DISPATCH_SHA256 or _sha(stdout_raw) != STDOUT_SHA256
            or repair_sources != REPAIRS):
        raise ValueError('Exact harness failure and repair sources required')
    journal = json.loads(dispatch_raw, object_pairs_hook=_pairs)
    receipt = journal.get('runner_summary', {}).get('receipt', {})
    test = receipt.get('test', {})
    if (journal.get('schema') != 1 or journal.get('phase') != 'inspection_required'
            or journal.get('returncode') != 1 or journal.get('validation_vm_stopped') is not True
            or journal.get('validation_passed') is not False
            or journal.get('manifest_sha256') != MANIFEST_SHA256
            or journal.get('sandbox_id') != UUID
            or journal.get('stdout_sha256') != STDOUT_SHA256
            or receipt.get('phase') != 'complete'
            or receipt.get('test_command_succeeded') is not False
            or test.get('reason') != 'exited' or test.get('returncode') != 1
            or test.get('reported_test_count') is not None
            or test.get('output_sha256') != TEST_OUTPUT_SHA256):
        raise ValueError('Not the fixed stopped harness-discovery failure')
    return {'schema': 1, 'outcome': 'validation_harness_failure_superseded',
        'dispatch_id': DISPATCH_ID, 'dispatch_sha256': DISPATCH_SHA256,
        'stdout_sha256': STDOUT_SHA256, 'manifest_sha256': MANIFEST_SHA256,
        'validation_vm_id': UUID, 'repair_sources': dict(REPAIRS),
        'validation_passed': False, 'candidate_accepted': False,
        'replay_permitted': False, 'model_start_authorized': False,
        'source_feedback_delivered': False, 'replacement_validation_required': True}


def verify_resolution(dispatch_raw, stdout_raw, resolution_raw):
    value = build_resolution(dispatch_raw, stdout_raw, REPAIRS)
    if resolution_raw != canonical(value):
        raise ValueError('Harness failure resolution changed')
    return value


def main():
    from validation_snapshot_dispatch import inventory
    require_managed_namespace()
    if os.environ.get('WSL_DISTRO_NAME') != 'EBase-Sandboxes' or os.getuid() != 1000:
        raise RuntimeError('Dedicated distro required')
    if not global_lock_held('/tmp/e-base-devin-fleet-global.lock'):
        raise RuntimeError('Global controller lock required')
    directory = ROOT / ('dispatch-' + DISPATCH_ID)
    values, vm = inventory()
    if any(value['status'] != 'stopped' for value in values) or vm['id'] != UUID:
        raise RuntimeError('All VMs must be stopped with exact validator identity')
    sources = {name: _sha(_file(ROOT / name, 1024 * 1024)) for name in REPAIRS}
    resolution = build_resolution(_file(directory / 'dispatch.json', 8 * 1024 * 1024),
                                  _file(directory / 'stdout.log', 8 * 1024 * 1024), sources)
    stored = persist_feedback(directory, resolution, filename='harness-failure-resolution.json')
    print(json.dumps({'path': stored['path'], 'sha256': stored['sha256'],
        'created': stored['created'], 'outcome': resolution['outcome'],
        'validation_passed': False, 'candidate_accepted': False}), flush=True)


if __name__ == '__main__':
    main()
