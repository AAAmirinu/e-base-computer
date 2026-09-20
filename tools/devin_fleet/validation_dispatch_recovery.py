"""Read-only fixed-probe recovery inspection. Never replays or starts a VM."""
import hashlib
import json
from validation_dispatch_receipt import _pairs, parse_summary


def _nonfinite(value):
    raise ValueError('Nonfinite JSON refused')


def inspect_record(raw, output, *, digest, image, base, expected_vm, live_vm):
    result = {'schema': 1, 'outcome': 'inspection_required', 'replay_permitted': False,
              'validation_passed': False}
    if not isinstance(raw, bytes) or len(raw) > 8 * 1024 * 1024:
        return dict(result, reason='invalid_journal_size')
    result['journal_sha256'] = hashlib.sha256(raw).hexdigest()
    try:
        journal = json.loads(raw.decode('utf-8', 'strict'), object_pairs_hook=_pairs,
                             parse_constant=_nonfinite)
        if not isinstance(journal, dict) or type(journal.get('schema')) is not int or journal['schema'] != 1:
            raise ValueError('Unknown journal schema')
        if any(journal.get(key) != value for key, value in {
                'sandbox_id': expected_vm, 'manifest_sha256': digest, 'image_id': image, 'base': base}.items()):
            raise ValueError('Identity mismatch')
        if not isinstance(live_vm, dict) or live_vm.get('id') != expected_vm or live_vm.get('status') != 'stopped':
            return dict(result, reason='vm_identity_or_stop_unverified')
        if journal.get('phase') != 'complete':
            return dict(result, reason='incomplete_dispatch_phase')
        if (journal.get('validation_vm_stopped') is not True or journal.get('validation_passed') is not False or
                type(journal.get('returncode')) is not int or journal['returncode'] != 0):
            raise ValueError('Invalid terminal claims')
        if not isinstance(output, bytes) or len(output) > 8 * 1024 * 1024:
            raise ValueError('Missing bounded output')
        if hashlib.sha256(output).hexdigest() != journal.get('stdout_sha256'):
            raise ValueError('Output hash mismatch')
        envelope = parse_summary(output, digest, image, base)
        if envelope != journal.get('runner_summary'):
            raise ValueError('Embedded summary mismatch')
        receipt = envelope['receipt']
        test = receipt.get('test')
        if (receipt.get('test_command_succeeded') is not True or not isinstance(test, dict) or
                type(test.get('returncode')) is not int or test['returncode'] != 0 or test.get('reason') != 'exited' or
                type(test.get('reported_test_count')) is not int or test['reported_test_count'] <= 0):
            raise ValueError('Successful nonempty test command not established')
        return dict(result, outcome='verified_completed_dispatch', reason='bound_result_and_stopped_vm',
                    operation=receipt['operation'], reported_test_count=test['reported_test_count'])
    except (ValueError, TypeError, KeyError, RecursionError):
        return dict(result, reason='invalid_or_inconsistent_evidence')


def main():
    import argparse
    import fcntl
    import os
    import re
    import stat
    from pathlib import Path
    from validation_snapshot_dispatch import inventory, DIGEST, IMAGE, UUID
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory')
    args = parser.parse_args()
    if os.environ.get('WSL_DISTRO_NAME') != 'EBase-Sandboxes' or os.getuid() != 1000:
        raise RuntimeError('Dedicated fleet user required')
    directory = Path(args.directory)
    if (directory.parent != Path('/home/fleet/controller-validation') or
            re.fullmatch('dispatch-[0-9a-f]{32}', directory.name) is None or directory.resolve() != directory):
        raise ValueError('Exact private dispatch directory required')
    metadata = directory.stat()
    if metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
        raise ValueError('Dispatch directory must be private and caller-owned')
    def read(name):
        fd = os.open(directory / name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            meta = os.fstat(stream.fileno())
            if (not stat.S_ISREG(meta.st_mode) or meta.st_nlink != 1 or meta.st_size > 8 * 1024 * 1024 or
                    meta.st_uid != os.getuid() or meta.st_mode & 0o022):
                raise ValueError('Unsafe receipt file')
            return stream.read(8 * 1024 * 1024 + 1)
    with open('/tmp/e-base-devin-fleet-global.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _, vm = inventory()
        raw = read('dispatch.json')
        try:
            output = read('stdout.log')
        except FileNotFoundError:
            output = None
        result = inspect_record(raw, output, digest=DIGEST, image=IMAGE,
            base='e7271a6eaca0204c77925ed6e5723412a1c4477e', expected_vm=UUID, live_vm=vm)
        print(json.dumps(result), flush=True)
        if result['outcome'] != 'verified_completed_dispatch':
            raise SystemExit(2)


if __name__ == '__main__':
    main()
