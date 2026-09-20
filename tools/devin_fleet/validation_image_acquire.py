"""One approved, bounded pull in validation VM only; restore denial on exit.

Requires explicit user authorization per invocation. Not a scheduler helper.
"""
import fcntl
import json
import os
import subprocess

SBX = ['sh', '/home/fleet/sbx-headless.sh']
NAME = 'e-base-validation'
UUID = '84a0fc99-4cbb-4383-a1df-4c22bbe0d2e6'
HOSTS = 'auth.docker.io:443,registry-1.docker.io:443,production.cloudfront.docker.com:443'
OLD_DENY = '3c875974-ac25-48cd-b5e1-e6ee013522fa'
IMAGE = 'node:22-bookworm-slim'


def run(*args, timeout=30, check=True):
    result = subprocess.run(SBX + list(args), capture_output=True, text=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError('Sandbox command failed: ' + result.stderr[:1000])
    return result


def allowed(host):
    result = run('policy', 'check', 'network', '--sandbox', NAME, '--json', host, check=False)
    return json.loads(result.stdout)['allowed']


def main():
    if os.environ.get('WSL_DISTRO_NAME') != 'EBase-Sandboxes' or os.getuid() != 1000:
        raise RuntimeError('Dedicated fleet user required')
    with open('/tmp/e-base-devin-fleet-global.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        inventory = json.loads(run('ls', '--json').stdout)['sandboxes']
        target = [s for s in inventory if s['name'] == NAME]
        if len(target) != 1 or target[0]['id'] != UUID or any(s['status'] != 'stopped' for s in inventory):
            raise RuntimeError('Identity or stopped-state gate failed')
        receipt = {'schema': 1, 'sandbox_id': UUID, 'image': IMAGE, 'allow_hosts': HOSTS}
        try:
            run('policy', 'allow', 'network', '--sandbox', NAME, HOSTS)
            run('policy', 'rm', 'network', '--sandbox', NAME, '--id', OLD_DENY)
            if allowed('example.com') is not False or allowed('registry-1.docker.io') is not True:
                raise RuntimeError('Scoped policy check failed')
            print('Scoped allow verified; starting bounded image pull', flush=True)
            pull = run('exec', NAME, 'timeout', '120', 'docker', 'pull', IMAGE, timeout=135, check=False)
            receipt['pull_returncode'] = pull.returncode
            # Progress contains hashes, not credential data. Do not emit signed URLs.
            receipt['pull_succeeded'] = pull.returncode == 0
            if pull.returncode == 0:
                info = run('exec', NAME, 'docker', 'image', 'inspect', IMAGE, '--format', '{{json .}}')
                image = json.loads(info.stdout)
                receipt['image_id'] = image['Id']
                receipt['repo_digests'] = image['RepoDigests']
                receipt['image_size'] = image['Size']
            else:
                receipt['failure_excerpt'] = (pull.stderr + pull.stdout).split('?')[0][-1000:]
        finally:
            try:
                run('policy', 'deny', 'network', '--sandbox', NAME, '**')
                run('policy', 'rm', 'network', '--sandbox', NAME, '--resource', HOSTS)
                receipt['network_denied_after'] = all(allowed(h) is False for h in ('example.com', 'registry-1.docker.io', 'auth.docker.io'))
            finally:
                run('stop', NAME)
                receipt['stopped_after'] = True
                print(json.dumps(receipt), flush=True)


if __name__ == '__main__':
    main()
