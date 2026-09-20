"""Operator-run active isolation probe in validation VM; trusted code only.

Leaves canary, receipt, and stopped container for evidence. Not a production
runner: caller must own the dedicated VM and shared fleet lock.
"""
import errno
import json
import os
from pathlib import Path
import subprocess
import uuid

from sandbox_validation_container import admit_image, create_arguments, verify_created_container, ENV
from validation_container_smoke import IMAGE, run

PROBE = r'''
import errno, json, os, pathlib, socket, subprocess, sys
canary = sys.argv[1]
result = {'canary_hidden': not os.path.lexists(canary)}
if not result['canary_hidden']:
    raise RuntimeError('VM canary visible')
try:
    fd = os.open('/validation-forbidden-write', os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
except OSError as error:
    result['root_write_errno'] = error.errno
    if error.errno != errno.EROFS:
        raise RuntimeError('Read-only root not established')
else:
    os.close(fd)
    raise RuntimeError('Root write unexpectedly succeeded')
pathlib.Path('/work/writable-probe').write_bytes(b'trusted scratch probe')
result['scratch_write_verified'] = pathlib.Path('/work/writable-probe').read_bytes() == b'trusted scratch probe'
if not result['scratch_write_verified']:
    raise RuntimeError('Scratch content mismatch')
result['connect_failures'] = []
for address in ('192.0.2.1', '127.0.0.1'):
    with socket.socket() as sock:
        sock.settimeout(1)
        try:
            sock.connect((address, 443))
        except OSError as error:
            if error.errno not in (errno.ENETUNREACH, errno.EHOSTUNREACH, errno.ECONNREFUSED):
                raise RuntimeError('Ambiguous connection failure')
            result['connect_failures'].append({'address': address, 'errno': error.errno})
        else:
            raise RuntimeError('Unexpected connection success')
limits = {name: pathlib.Path('/sys/fs/cgroup/' + name).read_text().strip()
          for name in ('memory.max', 'memory.swap.max', 'pids.max', 'cpu.max')}
assert limits['memory.max'] == '536870912', limits
assert limits['memory.swap.max'] == '0', limits
assert limits['pids.max'] == '64', limits
quota, period = limits['cpu.max'].split()
assert int(quota) == int(period) > 0, limits
result['cgroup_limits'] = limits
child = subprocess.Popen([sys.executable, '-I', '-c', 'import time; time.sleep(300)'],
                         start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
result['detached_child_pid'] = child.pid
print(json.dumps(result), flush=True)
'''


def process_identity(pid):
    try:
        value = Path('/proc/' + str(pid) + '/stat').read_text()
    except FileNotFoundError:
        return None
    # comm may contain spaces or parentheses. Fields after final ')' start at 3.
    return value.rsplit(')', 1)[1].split()[19]


def main():
    image = json.loads(run(['docker', 'image', 'inspect', IMAGE]))[0]
    admit_image(image)
    operation = uuid.uuid4().hex
    canary = Path('/tmp/validation-canary-' + operation)
    with canary.open('xb') as stream:
        stream.write(b'trusted nonsecret outer VM canary')
    canary.chmod(0o644)
    receipt_path = Path('/tmp/validation-active-' + operation + '.json')
    receipt = {'schema': 1, 'operation': operation, 'image_id': IMAGE,
               'container_name': 'e-base-check-' + operation, 'canary': str(canary), 'phase': 'prepared'}
    def save():
        temporary = receipt_path.with_suffix('.pending')
        with temporary.open('w', encoding='utf-8') as stream:
            json.dump(receipt, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, receipt_path)
    save()
    container = None
    identities = {}
    try:
        container = run(create_arguments(IMAGE, operation)).strip()
        receipt.update(container_id=container, phase='created')
        save()
        verify_created_container(json.loads(run(['docker', 'inspect', container]))[0], IMAGE, operation)
        run(['docker', 'start', container])
        boundary = Path('/tmp/validation_boundary_probe.py').read_text()
        prefix = ['docker', 'exec', container, '/usr/bin/env', '-i', *ENV, '/usr/local/bin/python3', '-I', '-c']
        receipt['boundary'] = json.loads(run(prefix + [boundary]))['result']
        receipt['active'] = json.loads(run(prefix + [PROBE, str(canary)]))
        rows = run(['docker', 'top', container, '-eo', 'pid']).splitlines()[1:]
        child_host_pids = []
        for row in rows:
            pid = int(row.strip())
            identity = process_identity(pid)
            if identity is None:
                raise RuntimeError('Process disappeared before stop observation')
            identities[pid] = identity
            status = Path('/proc/' + str(pid) + '/status').read_text()
            nspid = [line.split()[1:] for line in status.splitlines() if line.startswith('NSpid:')]
            if len(nspid) == 1 and nspid[0] and int(nspid[0][-1]) == receipt['active']['detached_child_pid']:
                child_host_pids.append(pid)
        if len(identities) < 2 or len(child_host_pids) != 1:
            raise RuntimeError('Detached child not visible to outer observer')
        receipt['detached_child_host_pid'] = child_host_pids[0]
        receipt.update(observed_processes=identities, phase='probed')
        save()
    finally:
        if container:
            run(['docker', 'stop', '--time', '2', container])
            state = json.loads(run(['docker', 'inspect', '--format', '{{json .State}}', container]))
            receipt['container_stopped'] = state['Running'] is False
            receipt['observed_processes_gone'] = bool(identities) and all(process_identity(pid) != start for pid, start in identities.items())
            receipt['canary_unchanged'] = canary.read_bytes() == b'trusted nonsecret outer VM canary'
            if receipt.get('phase') == 'probed' and all(receipt[k] for k in ('container_stopped', 'observed_processes_gone', 'canary_unchanged')):
                receipt['phase'] = 'complete'
            else:
                receipt['phase'] = 'inspection_required'
            save()
        print(json.dumps({'receipt_path': str(receipt_path), 'receipt': receipt}), flush=True)
    if receipt['phase'] != 'complete':
        raise RuntimeError('Active isolation probe incomplete')


if __name__ == '__main__':
    main()
