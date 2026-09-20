"""One reserved Git-image build in validation VM; temporary Debian HTTPS only."""
import base64
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import tarfile
import tempfile

import interactive_machine_auth as policy
from durable import atomic_write_json, _sync_directory
from managed_cli_guard import require_managed_namespace

ROOT = Path('/home/fleet/controller-validation')
HOSTS = {'deb.debian.org:443'}
BASE = 'sha256:1750198e508ceeabc96bb744de28bce36fe877ab0cd7f5a4a2eb0eff6d710f1f'


def new_allow_ids(before, after):
    def fixed(rows):
        return sorted(json.dumps({k: v for k, v in r.items() if k not in ('id', 'policy_id')}, sort_keys=True)
                      for r in rows if r.get('editable') is not True)
    old = {r['id']: r for r in before if r.get('editable') is True}
    current = {r['id']: r for r in after if r.get('editable') is True}
    if (len(old) != sum(r.get('editable') is True for r in before)
            or len(current) != sum(r.get('editable') is True for r in after) or fixed(before) != fixed(after)
            or any(current.get(key) != row for key, row in old.items())):
        raise RuntimeError('Existing network rules changed')
    created = [row for key, row in current.items() if key not in old]
    for row in created:
        if (row.get('resource_type') != 'network' or row.get('decision') != 'allow'
                or row.get('status') != 'active' or row.get('scope') != 'sandbox:e-base-validation'
                or row.get('applies_to') != 'sandbox:e-base-validation'
                or not isinstance(row.get('resources'), list) or not row['resources']
                or not set(row['resources']) <= HOSTS):
            raise RuntimeError('Unexpected new network allowance')
    return [row['id'] for row in created]


def build_context(root):
    files = {'Dockerfile': (root/'validation_git.Dockerfile').read_bytes(),
             'install_validation_git.py': (root/'install_validation_git.py').read_bytes()}
    if any(len(data) > 32768 for data in files.values()):
        raise ValueError('Oversize fixed build input')
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode='w') as output:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = len(data), 0o644, 0
            output.addfile(info, io.BytesIO(data))
    return archive.getvalue(), {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}


BUILD = r'''
import base64, hashlib, json, os, pathlib, resource, subprocess, tempfile
base = 'sha256:1750198e508ceeabc96bb744de28bce36fe877ab0cd7f5a4a2eb0eff6d710f1f'
tag = 'e-base-validation-git-base:' + base.split(':')[1]
def run(args):
    return subprocess.run(args, check=True, capture_output=True, timeout=30).stdout
work = pathlib.Path(tempfile.mkdtemp(prefix='e-base-git-image-build-'))
result = dict(base_image=base, build_directory=str(work), built=False)
try:
    if json.loads(run(['docker','image','inspect',base]))[0]['Id'] != base:
        raise RuntimeError('Base identity mismatch')
    found = run(['docker','image','ls','--no-trunc','--format','{{json .}}',
                 '--filter','reference='+tag]).decode().splitlines()
    if found:
        if len(found) != 1 or json.loads(run(['docker','image','inspect',tag]))[0]['Id'] != base:
            raise RuntimeError('Conflicting existing base tag')
    else:
        run(['docker','image','tag',base,tag])
    if json.loads(run(['docker','image','inspect',tag]))[0]['Id'] != base:
        raise RuntimeError('Base tag not verified')
    context = base64.b64decode(CONTEXT, validate=True)
    def limits():
        resource.setrlimit(resource.RLIMIT_FSIZE, (8*1024*1024, 8*1024*1024))
    with (work/'build.log').open('xb') as log:
        proc = subprocess.run(['docker','build','--pull=false','--network=default','--iidfile',str(work/'image-id'),'-'],
            input=context, stdout=log, stderr=subprocess.STDOUT, timeout=420, preexec_fn=limits)
    result['returncode'] = proc.returncode
    if proc.returncode == 0:
        identity = (work/'image-id').read_text().strip()
        info = json.loads(run(['docker','image','inspect',identity]))[0]
        if identity == base or info['Id'] != identity:
            raise RuntimeError('New image identity mismatch')
        result.update(built=True, image_id=identity, image_size=info['Size'])
except Exception as error:
    result['error_type'] = type(error).__name__
print(json.dumps(result), flush=True)
'''


def inspect_failed_build():
    """Read only the reserved first build log; never retry or reopen network."""
    require_managed_namespace()
    policy.NAME, policy.UUID = 'e-base-validation', '84a0fc99-4cbb-4383-a1df-4c22bbe0d2e6'
    with open('/tmp/e-base-devin-fleet-global.lock', 'r') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        policy.stopped()
        if not any(policy.scoped_deny(r) and r.get('resources') == ['**'] for r in policy.rules()):
            raise RuntimeError('Blanket denial required')
        if any(policy.allowed(h) is not False for h in HOSTS | {'example.com:443'}):
            raise RuntimeError('Denial not verified')
        source = """
import pathlib
path = pathlib.Path('/tmp/e-base-git-image-build-39ppmflc/build.log')
if path.is_symlink() or not path.is_file() or path.stat().st_size > 8*1024*1024:
    raise RuntimeError('Unexpected build log')
with path.open('rb') as stream:
    stream.seek(max(0, path.stat().st_size - 16000))
    print(stream.read(16000).decode('utf-8', errors='replace'))
"""
        try:
            print(policy.run('exec',policy.NAME,'/usr/bin/python3','-I','-c',source,timeout=60))
        finally:
            policy.run('stop',policy.NAME)
            policy.stopped()


def main():
    require_managed_namespace()
    policy.NAME, policy.UUID = 'e-base-validation', '84a0fc99-4cbb-4383-a1df-4c22bbe0d2e6'
    policy.HOSTS = HOSTS
    def interrupted(number, frame):
        raise KeyboardInterrupt('Build interrupted')
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, interrupted)
    context, inputs = build_context(ROOT)
    with open('/tmp/e-base-devin-fleet-global.lock', 'r') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        policy.stopped()
        original = policy.rules()
        denies = [r for r in original if policy.scoped_deny(r) and r.get('resources') == ['**']]
        allowed_hosts = {h for r in original if r.get('resource_type') == 'network'
                         and r.get('status') == 'active' and r.get('decision') == 'allow'
                         for h in r['resources']}
        if len(denies) != 1 or any('*' in h for h in allowed_hosts):
            raise RuntimeError('Exact restricted policy baseline required')
        previous_path = ROOT/'git-image-build-we0oqgmz/receipt.json'
        previous = json.loads(previous_path.read_text())
        if (previous.get('phase') != 'inspection_required' or previous.get('base_image') != BASE
                or previous.get('network_denied_after') is not True
                or previous.get('all_vms_stopped') is not True or previous.get('cleanup_errors') != []
                or previous.get('build', {}).get('built') is not False
                or previous.get('build', {}).get('returncode') != 1
                or previous.get('inputs') == inputs):
            raise RuntimeError('Prior failed build must be closed and recipe corrected')
        marker = ROOT/'git-image-build-v2.reservation'
        with marker.open('x') as handle:
            json.dump(dict(base=BASE, inputs=inputs), handle)
            handle.flush()
            os.fsync(handle.fileno())
        _sync_directory(ROOT)
        work = Path(tempfile.mkdtemp(prefix='git-image-build-', dir=ROOT))
        record = dict(schema=1, phase='prepared', base_image=BASE, inputs=inputs,
                      previous_attempt=str(previous_path),
                      sandbox_id=policy.UUID, model_executed=False, allowed_hosts=sorted(HOSTS))
        def save():
            atomic_write_json(work/'receipt.json', record)
        save()
        print('evidence=' + str(work), flush=True)
        allow_ids, deny_ids, opened = [], [], False
        try:
            if not HOSTS <= allowed_hosts:
                record['allow_ownership_verified'] = False
                save()
                policy.run('policy','allow','network','--sandbox',policy.NAME,','.join(sorted(HOSTS)))
            after_allow = policy.rules()
            allow_ids = new_allow_ids(original, after_allow)
            record['allow_ownership_verified'] = True
            blocked = sorted(allowed_hosts - HOSTS)
            if blocked:
                policy.run('policy','deny','network','--sandbox',policy.NAME,','.join(blocked))
                deny_ids = policy.restriction_ids(after_allow, policy.rules(), blocked)
            record.update(phase='restricted', temporary_allow_ids=allow_ids, temporary_deny_ids=deny_ids)
            save()
            opened = True
            policy.run('policy','rm','network','--sandbox',policy.NAME,'--id',denies[0]['id'])
            if (any(policy.allowed(h) is not True for h in HOSTS)
                    or any(policy.allowed(h) is not False for h in blocked + ['example.com:443','deb.debian.org:80'])):
                raise RuntimeError('Debian HTTPS-only policy not established')
            record['phase'] = 'building'
            save()
            source = 'CONTEXT=' + repr(base64.b64encode(context).decode()) + '\n' + BUILD
            record['build'] = json.loads(policy.run('exec',policy.NAME,'/usr/bin/python3','-I','-c',source,timeout=465))
        finally:
            for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
                signal.signal(sig, signal.SIG_IGN)
            errors = []
            try:
                if opened:
                    policy.run('policy','deny','network','--sandbox',policy.NAME,'**')
                if not any(policy.scoped_deny(r) and r.get('resources') == ['**'] for r in policy.rules()):
                    raise RuntimeError('Blanket deny missing')
                if any(policy.allowed(h) is not False for h in HOSTS | {'example.com:443'}):
                    raise RuntimeError('Denial not verified')
                record['network_denied_after'] = True
                for identity in allow_ids + deny_ids:
                    policy.run('policy','rm','network','--sandbox',policy.NAME,'--id',identity)
            except BaseException:
                errors.append('network_cleanup')
            try:
                policy.run('stop',policy.NAME)
                policy.stopped()
                record['all_vms_stopped'] = True
            except BaseException:
                errors.append('vm_cleanup')
            record.update(cleanup_errors=errors, phase='closed' if not errors and
                          record.get('build', {}).get('built') is True else 'inspection_required')
            save()
            print(json.dumps(record), flush=True)
        if record.get('cleanup_errors') or record.get('build', {}).get('built') is not True:
            raise RuntimeError('Image build incomplete; inspect without automatic retry')


if __name__ == '__main__':
    import sys
    if sys.argv[1:] == ['--inspect-failed-build']:
        inspect_failed_build()
    elif not sys.argv[1:]:
        main()
    else:
        raise ValueError('Unknown action')
