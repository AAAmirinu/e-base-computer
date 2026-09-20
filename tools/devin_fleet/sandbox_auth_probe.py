"""Read-only Devin authentication check in one stopped role VM; no login/model.

Only status classification is exported. Raw auth output stays in guest process
memory and is never printed or saved. Unknown output never implies admission.
"""
import argparse
import json
import os
from pathlib import Path
import tempfile

from sandbox_runtime import SandboxRuntime
from validation_snapshot_input import _file
from validation_dispatch_receipt import _pairs


PROBE = r'''
import json, subprocess
try:
    result = subprocess.run(['/home/agent/.local/bin/devin-cli', 'auth', 'status'],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=20)
    output = result.stdout.lower()
    status = 'not_logged_in' if b'not logged in' in output else 'unclassified'
    print(json.dumps({'status': status, 'returncode': result.returncode,
                      'raw_output_suppressed': True, 'model_executed': False}))
except subprocess.TimeoutExpired:
    print(json.dumps({'status': 'timeout', 'raw_output_suppressed': True,
                      'model_executed': False}))
'''


def main():
    from validation_snapshot_dispatch import inventory
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--role', required=True)
    parser.add_argument('--login-help', action='store_true', help='Print CLI login help only; never log in')
    parser.add_argument('--auth-hosts', action='store_true', help='Read built-in vendor hostnames only')
    args = parser.parse_args()
    if os.environ.get('WSL_DISTRO_NAME') != 'EBase-Sandboxes' or os.getuid() != 1000:
        raise RuntimeError('Dedicated distro required')
    root = Path('/home/fleet/controller-validation')
    registration = json.loads(_file(root / 'sandbox-registry.json', 1024*1024), object_pairs_hook=_pairs)
    if args.role not in registration['roles']:
        raise ValueError('Unknown role')
    work = Path(tempfile.mkdtemp(prefix='auth-status-', dir=root))
    print('evidence=' + str(work), flush=True)
    with SandboxRuntime(registration, work) as runtime:
        if any(v['status'] != 'stopped' for v in inventory()[0]):
            raise RuntimeError('All VMs must be stopped')
        with runtime.role(args.role) as repo:
            command = (['/home/agent/.local/bin/devin-cli', 'auth', 'login', '--help']
                       if args.login_help else ['python3', '-I', '-c', PROBE])
            if args.auth_hosts:
                command = ['/usr/bin/python3', '-I', '-c',
                    "import re,json; b=open('/home/agent/.local/bin/devin-cli','rb').read(256*1024*1024); "
                    "hosts=sorted(set(x.decode() for x in re.findall(rb'https://([a-zA-Z0-9.-]+)',b) "
                    "if x.endswith((b'.devin.ai',b'.codeium.com',b'.windsurf.com',b'.auth0.com')))); print(json.dumps(hosts))"]
            result = repo.controller.execute(command,
                cwd=repo.guest_root, log_path=work / 'status.log', timeout=30)
            if result.returncode:
                raise RuntimeError('Auth status probe failed')
        print((work / 'status.log').read_text(), flush=True)
        print(json.dumps({'all_vms_stopped': all(v['status'] == 'stopped' for v in inventory()[0])}), flush=True)


if __name__ == '__main__':
    main()
