"""Validation VM operator probe: source executed only inside checked container."""
import base64
import hashlib
import json
import os
from pathlib import Path
import selectors
import re
import subprocess
import sys
import time
import uuid

from sandbox_snapshot_receiver import validate_snapshot
from sandbox_validation_container import admit_image, create_arguments, verify_created_container, ENV
from validation_container_smoke import IMAGE, run
from validation_snapshot_input import digest_argument

DIGEST = '11ae09248ff91a77e069ff7eaf6921b9247d1a6cc63897399a78fbbc6782febc'
TEST_TIMEOUT = 120
TEST_OUTPUT_LIMIT = 1024 * 1024


def test_arguments(container, fixed_prepared_trial=False):
    """Return one of two fixed test profiles; never accept caller commands."""
    if type(fixed_prepared_trial) is not bool:
        raise TypeError('Fixed prepared trial selector must be boolean')
    base = ['docker', 'exec', '--workdir', '/work/source', container,
            '/usr/bin/env', '-i', *ENV, '/usr/local/bin/python3', '-B', '-m', 'unittest']
    if fixed_prepared_trial:
        return base + ['-v', 'test_add']
    return base + ['discover', '-s', 'tests', '-v']


def bounded_test(arguments):
    """Bound combined output and elapsed time; caller always stops container."""
    process = subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               stdin=subprocess.DEVNULL)
    output = bytearray()
    deadline = time.monotonic() + TEST_TIMEOUT
    selector = None
    reason = 'exited'
    try:
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        while selector.get_map():
            if time.monotonic() >= deadline:
                reason = 'timeout'
                break
            for key, _ in selector.select(min(0.2, max(0, deadline - time.monotonic()))):
                chunk = os.read(key.fd, 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                room = TEST_OUTPUT_LIMIT - len(output)
                output.extend(chunk[:room])
                if len(chunk) > room:
                    reason = 'output_limit'
                    break
            if reason != 'exited':
                break
        if reason == 'exited':
            try:
                process.wait(timeout=max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                reason = 'timeout'
    finally:
        if process.poll() is None:
            process.kill()
        try:
            process.wait(timeout=5)
        finally:
            if selector is not None:
                selector.close()
            process.stdout.close()
    return {'returncode': process.returncode, 'reason': reason,
            'output_sha256': hashlib.sha256(output).hexdigest(), 'output': output.decode('utf-8', 'replace')}


def finish_container(container, receipt, save):
    """Journal cleanup before acting; failure never preserves a success claim."""
    prior_phase = receipt.get('phase')
    receipt.update(phase='cleanup_pending', phase_before_cleanup=prior_phase,
                   validation_passed=False, test_command_succeeded=False, container_stopped=False)
    try:
        try:
            save()
        finally:
            # A disk/fsync failure must never prevent attempting containment.
            run(['docker', 'stop', '--time', '2', container])
        state = json.loads(run(['docker', 'inspect', '--format', '{{json .State}}', container]))
        if state.get('Running') is not False:
            raise RuntimeError('Container still running after stop')
        receipt['container_stopped'] = True
        test = receipt.get('test', {})
        receipt['test_command_succeeded'] = (prior_phase == 'tested' and test.get('reason') == 'exited' and
            test.get('returncode') == 0 and (test.get('reported_test_count') or 0) > 0)
        receipt['phase'] = 'complete' if prior_phase == 'tested' else 'inspection_required'
        save()
    except BaseException as error:
        receipt.update(phase='cleanup_failed', validation_passed=False, test_command_succeeded=False,
                       cleanup_error_type=type(error).__name__)
        save()
        raise


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest-sha256', type=digest_argument, required=True)
    parser.add_argument('--git-image-candidate', action='store_true')
    parser.add_argument('--fixed-prepared-trial-test', action='store_true')
    args = parser.parse_args()
    expected_digest = args.manifest_sha256
    image = IMAGE
    if args.git_image_candidate:
        image = 'sha256:cee9fe9272c17a34c0b1620485843ff67431dcc18d2e0f7380581fe28f5aeaf4'
    raw_packet = sys.stdin.buffer.read(32 * 1024 * 1024 + 1)
    if len(raw_packet) > 32 * 1024 * 1024:
        raise ValueError('Packet exceeds bound')
    packet = json.loads(raw_packet)
    raw = base64.b64decode(packet['manifest'], validate=True)
    blobs = {k: base64.b64decode(v, validate=True) for k, v in packet['blobs'].items()}
    manifest = validate_snapshot(raw, expected_digest, blobs)
    admit_image(json.loads(run(['docker', 'image', 'inspect', image]))[0])
    operation = uuid.uuid4().hex
    receipt_path = Path('/tmp/validation-source-' + operation + '.json')
    receipt = {'schema': 1, 'operation': operation, 'manifest_sha256': expected_digest,
               'base': manifest['base'], 'image_id': image, 'phase': 'prepared',
               'container_name': 'e-base-check-' + operation,
               'test_profile': ('fixed-prepared-test-add-v1' if args.fixed_prepared_trial_test
                                else 'default-discovery-v1')}
    def save():
        temp = receipt_path.with_suffix('.pending')
        with temp.open('w') as stream:
            json.dump(receipt, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, receipt_path)
        directory_fd = os.open(receipt_path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    save()
    container = None
    try:
        container = run(create_arguments(image, operation)).strip()
        receipt.update(container_id=container, phase='created')
        save()
        verify_created_container(json.loads(run(['docker', 'inspect', container]))[0], image, operation)
        run(['docker', 'start', container])
        prefix = ['docker', 'exec', container, '/usr/bin/env', '-i', *ENV, '/usr/local/bin/python3', '-I', '-c']
        receipt['boundary'] = json.loads(run(prefix + [Path('/tmp/validation_boundary_probe.py').read_text()]))['result']
        receipt['node_version'] = run(['docker', 'exec', container, '/usr/bin/env', '-i', *ENV,
                                      '/usr/local/bin/node', '--version']).strip()
        receiver = Path('/tmp/sandbox_snapshot_receiver.py').read_text()
        bootstrap = receiver + '''
import base64, sys
p = json.loads(sys.stdin.buffer.read(33554433))
r = base64.b64decode(p['manifest'], validate=True)
b = {k: base64.b64decode(v, validate=True) for k,v in p['blobs'].items()}
print(json.dumps(materialize_snapshot('/work', 'source', r, sys.argv[1], b)))
'''
        staged = subprocess.run(['docker', 'exec', '-i', container, '/usr/bin/env', '-i', *ENV,
                                 '/usr/local/bin/python3', '-I', '-c', bootstrap, expected_digest],
                                input=raw_packet, capture_output=True, timeout=30)
        if staged.returncode:
            raise RuntimeError('Source materialization refused: ' + staged.stderr.decode()[:1000])
        receipt['materialization'] = json.loads(staged.stdout)
        receipt['phase'] = 'source_ready'
        save()
        # Source may now execute, but only in the checked credential-free container.
        receipt['phase'] = 'testing'
        save()
        receipt['test'] = bounded_test(test_arguments(container, args.fixed_prepared_trial_test))
        match = re.search(r'Ran (\d+) tests? in ', receipt['test']['output'])
        receipt['test']['reported_test_count'] = int(match.group(1)) if match else None
        receipt['test']['skip_lines'] = [line for line in receipt['test']['output'].splitlines() if '... skipped ' in line]
        receipt['phase'] = 'tested'
        save()
    finally:
        if container:
            finish_container(container, receipt, save)
        display = dict(receipt)
        if 'test' in display:
            display['test'] = dict(display['test'])
            display['test']['output_tail'] = display['test'].pop('output')[-400:]
        print(json.dumps({'receipt_path': str(receipt_path), 'receipt': display}), flush=True)
    if not receipt.get('test_command_succeeded'):
        raise RuntimeError('Test command failed, timed out, or reported no tests')


if __name__ == '__main__':
    main()
