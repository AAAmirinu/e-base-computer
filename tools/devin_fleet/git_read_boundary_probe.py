"""Synthetic-only real Git probe, executed only inside checked validation container."""
SOURCE = r'''
import base64, json, os, pathlib, subprocess, sys
if os.getuid() != 65532 or not pathlib.Path('/.dockerenv').is_file():
    raise RuntimeError('Credential-free validation container required')
env = {'PATH':'/usr/bin:/bin', 'HOME':'/home/agent', 'LC_ALL':'C.UTF-8'}
def git(root, *args):
    return subprocess.run(['/usr/bin/git', '-C', str(root), *args], env=env,
        stdin=subprocess.DEVNULL, capture_output=True, check=True, timeout=10).stdout
def fresh(name):
    root = pathlib.Path('/work')/name
    root.mkdir()
    git(root, 'init', '--quiet')
    git(root, 'config', 'user.name', 'Synthetic boundary probe')
    git(root, 'config', 'user.email', 'probe@localhost')
    (root/'data.txt').write_bytes(b'initial\n')
    git(root, 'add', 'data.txt')
    git(root, 'commit', '-m', 'Synthetic Git read boundary')
    return root
def read(root, args, *, extra_env=None, limit=65536):
    request = dict(operation='git_read', root=str(root), limit=limit, args=args)
    marker = 'PROBE_RESULT:'
    result = subprocess.run([sys.executable, '-I', '-c', REPOSITORY_CODE, marker, json.dumps(request)],
        env=dict(env, **(extra_env or {})), stdin=subprocess.DEVNULL, capture_output=True, check=True, timeout=15)
    if len(result.stdout)+len(result.stderr) > 100000:
        raise ValueError('Probe output exceeds bound')
    lines = [line[len(marker):] for line in result.stdout.decode().splitlines() if line.startswith(marker)]
    if len(lines) != 1:
        raise ValueError('Ambiguous repository response')
    response = json.loads(lines[0])
    return response['ok'], base64.b64decode(response['data'], validate=True)
root = fresh('read-normal')
head = git(root, 'rev-parse', 'HEAD')
(root/'data.txt').write_bytes(b'changed\n')
(root/'new.txt').write_bytes(b'untracked\n')
checks = [(['rev-parse','HEAD'],head), (['ls-files','-z'],b'data.txt\0'),
          (['ls-files','--others','--exclude-standard','-z'],b'new.txt\0'),
          (['diff','--no-renames','--name-only','-z','HEAD'],b'data.txt\0')]
for args, expected in checks:
    ok, data = read(root,args)
    if ok is not True or data != expected:
        raise RuntimeError('Normal read failed')
blocked = []
for index, key in enumerate(('filter.probe.clean','filter.probe.process','core.fsmonitor',
                             'diff.external','diff.probe.textconv','include.path','commit.gpgsign')):
    root = fresh('read-reject-'+str(index))
    canary = pathlib.Path('/work/canary-'+str(index))
    value = 'touch '+str(canary)
    if key == 'core.fsmonitor':
        script = pathlib.Path('/work/fsmonitor-canary.sh')
        script.write_text('#!/bin/sh\n/usr/bin/touch '+str(canary)+'\n')
        script.chmod(0o755)
        value = str(script)
    if key == 'include.path':
        # A FIFO would hang enumeration if the include were followed.
        fifo = pathlib.Path('/work/include-fifo')
        os.mkfifo(fifo)
        value = str(fifo)
    if key == 'commit.gpgsign':
        value = 'true'
    git(root, 'config', key, value)
    if key.startswith('filter.'):
        (root/'.gitattributes').write_text('data.txt filter=probe\n')
    if key == 'diff.probe.textconv':
        (root/'.gitattributes').write_text('data.txt diff=probe\n')
    (root/'data.txt').write_bytes(b'changed\n')
    ok, data = read(root,['diff','--no-renames','--name-only','-z','HEAD'])
    if ok is not False or data or canary.exists():
        raise RuntimeError('Unsafe configuration was not refused')
    blocked.append(key)
def refused(root, args, **options):
    ok, data = read(root, args, **options)
    if ok is not False or data:
        raise RuntimeError('Unsafe read boundary was not refused')
root = fresh('read-env')
env_cases = [dict(GIT_CONFIG_COUNT='1', GIT_CONFIG_KEY_0='core.fsmonitor',
                  GIT_CONFIG_VALUE_0='touch /work/env-canary'),
             dict(LD_BIND_NOW='1'), dict(XDG_CONFIG_HOME='/work/foreign-config'),
             dict(HOME='/work')]
for changes in env_cases:
    refused(root, ['rev-parse','HEAD'], extra_env=changes)
if pathlib.Path('/work/env-canary').exists():
    raise RuntimeError('Injected configuration executed')
# Demonstrate the same repository still works without injected environment.
if read(root,['rev-parse','HEAD']) != (True,git(root,'rev-parse','HEAD')):
    raise RuntimeError('Environment test lacks valid control')
refused(root,['rev-parse','HEAD'],limit=8)
root = fresh('read-gitlink')
commit = git(root,'rev-parse','HEAD').decode().strip()
git(root,'update-index','--add','--cacheinfo','160000,'+commit+',nested')
if b'160000 '+commit.encode()+b' 0\tnested\0' not in git(root,'ls-files','--stage','-z'):
    raise RuntimeError('Synthetic gitlink setup failed')
refused(root,['diff','--no-renames','--name-only','-z','HEAD'])
root = fresh('read-linked-metadata')
(root/'.git').rename(root/'metadata')
(root/'.git').symlink_to(root/'metadata', target_is_directory=True)
refused(root,['rev-parse','HEAD'])
root = fresh('read-oversize-config')
git(root,'config','user.name','x'*70000)
refused(root,['rev-parse','HEAD'])
# Positive control: the marker location is writable and the synthetic command
# works in this container. It never runs against a real project or credential.
control = pathlib.Path('/work/positive-control')
subprocess.run(['/usr/bin/touch',str(control)], check=True, timeout=5)
if not control.is_file():
    raise RuntimeError('Canary positive control failed')
print(json.dumps(dict(git_read_policy_verified=True, normal_read_count=len(checks),
    rejected_config_keys=blocked, canaries_absent=True, positive_control=True,
    include_not_followed=True, rejected_environment_cases=len(env_cases),
    gitlink_rejected=True, linked_metadata_rejected=True, command_output_limit_verified=True,
    config_output_limit_verified=True, timeout_cleanup_verified=False,
    synthetic_only=True, project_source_executed=False)))
'''
