"""Fixed synthetic Git commit in a fresh credential-free container, no project."""
import fcntl
import json
from pathlib import Path
import subprocess
import tempfile

from durable import atomic_write_json
from managed_cli_guard import require_managed_namespace
from validation_snapshot_dispatch import inventory, SBX

GUEST = r'''
import json, os, sys
sys.path.insert(0, '/tmp')
from sandbox_validation_container import admit_image, create_arguments, verify_created_container, ENV
from validation_container_smoke import IMAGE, run
import uuid
if NEW_IMAGE is not None:
    IMAGE = NEW_IMAGE

operation = uuid.uuid4().hex
receipt = dict(operation=operation, image_id=IMAGE, synthetic_only=True,
               project_source_executed=False, model_executed=False, passed=False,
               container_stopped=False, mode='image_info' if INFO_ONLY else 'git_commit')
container = None
try:
    admit_image(json.loads(run(['docker','image','inspect',IMAGE]))[0])
    container = run(create_arguments(IMAGE, operation)).strip()
    receipt['container_id'] = container
    verify_created_container(json.loads(run(['docker','inspect',container]))[0], IMAGE, operation)
    run(['docker','start',container])
    probe = r"""
import json, os, pathlib, shutil, subprocess, sys
git = shutil.which('git')
if not git:
    print(json.dumps(dict(git_available=False, commit_verified=False)))
else:
    def command(*args):
        env = dict(os.environ, GIT_AUTHOR_DATE='2000-01-01T00:00:00+00:00',
                   GIT_COMMITTER_DATE='2000-01-01T00:00:00+00:00')
        return subprocess.run([git, *args], check=True, capture_output=True, timeout=15, env=env).stdout
    version = command('--version').decode().strip()
    # Inspect instead of overriding hooks/signing/security settings.
    if command('config', '--list', '--name-only').strip():
        raise RuntimeError('Unexpected inherited Git configuration')
    root = '/work/git-capability'
    command('init', root)
    hooks = pathlib.Path(root) / '.git/hooks'
    if hooks.exists() and any(not p.name.endswith('.sample') or not p.is_file() or p.is_symlink()
                              for p in hooks.iterdir()):
        raise RuntimeError('Unexpected active Git hook')
    command('-C', root, 'config', 'user.name', 'E-base Synthetic Validation')
    command('-C', root, 'config', 'user.email', 'validation@localhost')
    path = pathlib.Path(root) / 'probe.txt'
    path.write_bytes(b'EBASE_GIT_CAPABILITY\n')
    command('-C', root, 'add', '--', 'probe.txt')
    command('-C', root, 'commit', '-m', 'Synthetic validation capability only')
    commit = command('-C', root, 'rev-parse', 'HEAD').decode().strip()
    content = command('-C', root, 'show', 'HEAD:probe.txt')
    tree = command('-C', root, 'ls-tree', '--name-only', 'HEAD') == b'probe.txt\n'
    clean = command('-C', root, 'status', '--porcelain') == b''
    node = subprocess.run(['/usr/local/bin/node', '--version'], check=True,
                          capture_output=True, text=True, timeout=15).stdout.strip()
    metadata = json.loads(pathlib.Path('/usr/local/share/e-base/git-build.json').read_text()) if NEW_METADATA else None
    print(json.dumps(dict(git_available=True, git_version=version, commit=commit,
                         python_version=sys.version.split()[0], node_version=node, build_metadata=metadata,
                         uid=os.getuid(), commit_verified=content == b'EBASE_GIT_CAPABILITY\n' and clean and tree)))
"""
    probe = 'NEW_METADATA=' + repr(NEW_IMAGE is not None) + '\n' + probe
    if INFO_ONLY:
        probe = r"""
import json, pathlib, platform, shutil, urllib.parse
release = platform.freedesktop_os_release()
sources = []
source_fields = []
for name in ('/etc/apt/sources.list.d/debian.sources', '/etc/apt/sources.list'):
    path = pathlib.Path(name)
    if path.is_file():
        text = path.read_text()
        if len(text) > 65536:
            raise ValueError('Unexpected apt source size')
        for line in text.splitlines():
            if line.startswith(('Types:', 'Suites:', 'Components:', 'Signed-By:')):
                source_fields.append(line)
            if line.startswith('URIs:'):
                for url in line[5:].split():
                    parsed = urllib.parse.urlsplit(url)
                    if parsed.username or parsed.password:
                        raise ValueError('Unexpected source credentials')
                    sources.append(dict(scheme=parsed.scheme, host=parsed.hostname, path=parsed.path))
print(json.dumps(dict(os_id=release.get('ID'), version_id=release.get('VERSION_ID'),
                     codename=release.get('VERSION_CODENAME'), apt_available=bool(shutil.which('apt-get')),
                     sources=sources, source_fields=source_fields,
                     git_available=bool(shutil.which('git')), commit_verified=False)))
"""
    if READ_POLICY_PROBE is not None:
        probe = READ_POLICY_PROBE
        receipt['mode'] = 'git_read_policy'
    receipt['probe'] = json.loads(run(['docker','exec',container,'/usr/bin/env','-i',*ENV,
                                     '/usr/local/bin/python3','-I','-c',probe]))
    receipt['passed'] = (receipt['probe'].get('git_read_policy_verified') is True if READ_POLICY_PROBE is not None else
                        receipt['probe'].get('apt_available') is True if INFO_ONLY else
                         receipt['probe'].get('commit_verified') is True)
except Exception as error:
    receipt.update(passed=False, error_type=type(error).__name__)
finally:
    if container:
        try:
            run(['docker','stop','--time','2',container])
            state = json.loads(run(['docker','inspect','--format','{{json .State}}',container]))
            receipt['container_stopped'] = state.get('Running') is False
        except Exception as error:
            receipt.update(passed=False, cleanup_error_type=type(error).__name__)
    if not receipt['container_stopped']:
        receipt['passed'] = False
    print(json.dumps(receipt), flush=True)
'''


def main(*, info_only=False, new_git_image=False, active_probe=False, read_policy_probe=False):
    require_managed_namespace()
    selected = None
    if new_git_image:
        selected = 'sha256:cee9fe9272c17a34c0b1620485843ff67431dcc18d2e0f7380581fe28f5aeaf4'
        build = json.loads(Path('/home/fleet/controller-validation/git-image-build-edfcfgb7/receipt.json').read_text())
        if (build.get('phase') != 'closed' or build.get('network_denied_after') is not True
                or build.get('all_vms_stopped') is not True or build.get('cleanup_errors') != []
                or build.get('build', {}).get('built') is not True
                or build['build'].get('image_id') != selected):
            raise RuntimeError('Closed successful fixed build required')
    with open('/tmp/e-base-devin-fleet-global.lock', 'r') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        rows, _ = inventory()
        if len(rows) != 11 or any(row.get('status') != 'stopped' for row in rows):
            raise RuntimeError('All eleven VMs must be stopped')
        policy = subprocess.run(SBX + ['policy','check','network','--sandbox','e-base-validation',
            '--json','registry-1.docker.io'], capture_output=True, text=True, timeout=30)
        if json.loads(policy.stdout).get('allowed') is not False:
            raise RuntimeError('Validator network denial required')
        work = Path(tempfile.mkdtemp(prefix='git-capability-', dir='/home/fleet/controller-validation'))
        receipt = dict(schema=1, phase='prepared', model_executed=False)
        def save():
            atomic_write_json(work/'receipt.json', receipt)
        save()
        print('evidence=' + str(work), flush=True)
        try:
            receipt['phase'] = 'running'
            save()
            probe = None
            if read_policy_probe:
                if not new_git_image or info_only or active_probe:
                    raise ValueError('Read policy probe requires fixed Git image only')
                from sandbox_repository import _GUEST_CODE
                from git_read_boundary_probe import SOURCE
                probe = 'REPOSITORY_CODE='+repr(_GUEST_CODE)+'\n'+SOURCE
            source = ('INFO_ONLY=' + repr(info_only) + '\nNEW_IMAGE=' + repr(selected)
                      + '\nREAD_POLICY_PROBE='+repr(probe)+'\n' + GUEST)
            if active_probe:
                if not new_git_image or info_only:
                    raise ValueError('Active probe requires the fixed candidate image')
                code = Path('/home/fleet/controller-validation/validation_active_smoke.py').read_text()
                if len(code) > 32768:
                    raise ValueError('Oversize trusted probe')
                source = ("import sys, types; sys.path.insert(0, '/tmp'); "
                          "m=types.ModuleType('trusted_active_probe'); exec(compile(" + repr(code) +
                          ", '<trusted-active-probe>', 'exec'), m.__dict__); m.IMAGE=" + repr(selected) + "; m.main()")
            result = subprocess.run(SBX + ['exec','e-base-validation','/usr/bin/python3','-I','-c',source],
                capture_output=True, timeout=180, check=True)
            if len(result.stdout) > 32768:
                raise RuntimeError('Oversize capability result')
            receipt['capability'] = json.loads(result.stdout)
            if active_probe:
                evidence = receipt['capability']
                observed = evidence.get('receipt', {})
                receipt['capability'] = dict(active_evidence=evidence, passed=(
                    observed.get('phase') == 'complete' and observed.get('image_id') == selected
                    and observed.get('container_stopped') is True
                    and observed.get('observed_processes_gone') is True
                    and observed.get('canary_unchanged') is True
                    and observed.get('boundary', {}).get('observations_verified') is True
                    and observed.get('boundary', {}).get('full_isolation_accepted') is False))
            receipt['phase'] = 'result_received'
        finally:
            try:
                subprocess.run(SBX + ['stop','e-base-validation'], check=True, capture_output=True, timeout=30)
                rows, _ = inventory()
                if len(rows) != 11 or any(row.get('status') != 'stopped' for row in rows):
                    raise RuntimeError('Final VM stop not verified')
                receipt['all_vms_stopped'] = True
                receipt['phase'] = 'closed' if receipt.get('capability', {}).get('passed') is True else 'inspection_required'
            finally:
                save()
                print(json.dumps(receipt), flush=True)
        if receipt['phase'] != 'closed':
            raise RuntimeError('Git capability not established')


if __name__ == '__main__':
    import sys
    if sys.argv[1:] == ['--image-info']:
        main(info_only=True)
    elif sys.argv[1:] == ['--new-git-image']:
        main(new_git_image=True)
    elif sys.argv[1:] == ['--new-git-active']:
        main(new_git_image=True, active_probe=True)
    elif sys.argv[1:] == ['--git-read-policy']:
        main(new_git_image=True, read_policy_probe=True)
    elif not sys.argv[1:]:
        main()
    else:
        raise ValueError('Unknown fixed action')
