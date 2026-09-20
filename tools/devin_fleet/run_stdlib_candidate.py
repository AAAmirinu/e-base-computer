"""One reserved maintenance candidate build in the credential-free validator."""
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import resource
import re
import signal
import subprocess
import tempfile

from durable import atomic_write_json, _sync_directory
from managed_cli_guard import require_managed_namespace
from validation_snapshot_dispatch import inventory, SBX
from validation_snapshot_input import load_snapshot
from validation_dispatch_receipt import parse_summary
from snapshot_git_tree import expected_tree
from candidate_packet import prepare_build, prepare_import
import interactive_machine_auth as policy

ROOT = Path('/home/fleet/controller-validation')
IMAGE = 'sha256:cee9fe9272c17a34c0b1620485843ff67431dcc18d2e0f7380581fe28f5aeaf4'
DIGEST = '6039785fee9ba2a0425c41b6999e0fa082abe49310f47e0124ab9d204ad070ff'
PARENT_BUNDLE = 'fa7c9186279947622c9cf3e9f60d1b28e8881aa0305392516009abd4463f8078'

INNER = r'''
import base64, json, sys, types
packet = json.loads(sys.stdin.buffer.read(33554433))
for name in ('sandbox_snapshot_receiver', 'snapshot_git_tree', 'container_candidate_commit'):
    source = packet['modules'][name]
    module = types.ModuleType(name)
    sys.modules[name] = module
    exec(compile(source, '<trusted-'+name+'>', 'exec'), module.__dict__)
from container_candidate_commit import build_candidate, verify_import
decode = lambda value: base64.b64decode(value, validate=True)
if packet.get('verify_import') is True:
    metadata, bundle = verify_import(decode(packet['manifest']), packet['digest'],
        {key:decode(value) for key,value in packet['blobs'].items()}, decode(packet['candidate_bundle']),
        packet['candidate_metadata'])
else:
    metadata, bundle = build_candidate(decode(packet['manifest']), packet['digest'],
        {key:decode(value) for key,value in packet['blobs'].items()}, decode(packet['parent_bundle']),
        packet['parent_bundle_sha256'], packet['parent_ref'])
print(json.dumps(dict(metadata=metadata, bundle=base64.b64encode(bundle).decode())))
'''

GUEST = r'''
import json, pathlib, subprocess, sys, uuid
sys.path.insert(0, '/tmp')
from sandbox_validation_container import admit_image, create_arguments, verify_created_container, ENV
from validation_container_smoke import run
packet = sys.stdin.buffer.read(33554433)
if len(packet) > 33554432:
    raise ValueError('Oversize packet')
admit_image(json.loads(run(['docker','image','inspect',IMAGE]))[0])
operation = uuid.uuid4().hex
container = None
receipt = dict(image_id=IMAGE, operation=operation, passed=False, container_stopped=False)
try:
    container = run(create_arguments(IMAGE, operation)).strip()
    receipt['container_id'] = container
    verify_created_container(json.loads(run(['docker','inspect',container]))[0], IMAGE, operation)
    run(['docker','start',container])
    prefix = ['docker','exec',container,'/usr/bin/env','-i',*ENV,'/usr/local/bin/python3','-I','-c']
    receipt['boundary'] = json.loads(run(prefix + [pathlib.Path('/tmp/validation_boundary_probe.py').read_text()]))['result']
    result = subprocess.run(['docker','exec','-i',container,'/usr/bin/env','-i',*ENV,
        '/usr/local/bin/python3','-I','-c',INNER], input=packet, capture_output=True, timeout=120)
    if result.returncode or len(result.stdout) > 24*1024*1024:
        receipt['inner_error_tail'] = result.stderr.decode('utf-8', 'replace')[-2000:]
        raise RuntimeError('Candidate command failed')
    receipt['candidate'] = json.loads(result.stdout)
    receipt['passed'] = True
except Exception as error:
    receipt['error_type'] = type(error).__name__
finally:
    if container:
        run(['docker','stop','--time','2',container])
        state = json.loads(run(['docker','inspect','--format','{{json .State}}',container]))
        receipt['container_stopped'] = state.get('Running') is False
    receipt['passed'] = receipt['passed'] and receipt['container_stopped']
    print(json.dumps(receipt), flush=True)
'''


def inputs():
    raw, blobs, manifest = load_snapshot(ROOT/'stdlib-main-snapshot-6gprve05', DIGEST)
    dispatch_dir = ROOT/'dispatch-7e3e23afef9f4a1d8edd71f7688c3704'
    dispatch_raw = (dispatch_dir/'dispatch.json').read_bytes()
    dispatch = json.loads(dispatch_raw)
    stdout = (dispatch_dir/'stdout.log').read_bytes()
    summary = parse_summary(stdout, DIGEST, IMAGE, manifest['base'])
    result = summary['receipt']
    test = result.get('test', {})
    if (dispatch.get('phase') != 'complete' or dispatch.get('returncode') != 0
            or dispatch.get('validation_vm_stopped') is not True
            or dispatch.get('stdout_sha256') != hashlib.sha256(stdout).hexdigest()
            or dispatch.get('runner_summary') != summary
            or result.get('test_command_succeeded') is not True
            or result.get('boundary', {}).get('observations_verified') is not True
            or test.get('returncode') != 0 or test.get('reason') != 'exited'
            or test.get('reported_test_count') != 203 or test.get('skip_lines') != []
            or not test.get('output_tail', '').endswith('\nOK\n')):
        raise RuntimeError('Fixed successful validation evidence required')
    bundle = (ROOT/'validation-parent-main-v1.bundle').read_bytes()
    if len(bundle) != 474030 or hashlib.sha256(bundle).hexdigest() != PARENT_BUNDLE:
        raise ValueError('Parent bundle digest mismatch')
    modules = {}
    for name in ('sandbox_snapshot_receiver', 'snapshot_git_tree', 'container_candidate_commit'):
        code = (ROOT/(name+'.py')).read_text()
        if len(code) > 32768:
            raise ValueError('Oversize trusted module')
        modules[name] = code
    packet, expected = prepare_build(raw, DIGEST, blobs, bundle, PARENT_BUNDLE,
                                    'refs/heads/fleet/integration', modules)
    return packet, expected, hashlib.sha256(dispatch_raw).hexdigest()


def main(*, import_check=False):
    require_managed_namespace()
    def interrupted(number, frame):
        raise KeyboardInterrupt('Candidate build interrupted')
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, interrupted)
    packet, expected, dispatch_sha = inputs()
    origin_sha = None
    if import_check:
        origin = ROOT/'stdlib-candidate-as9h24h6'
        origin_raw = (origin/'receipt.json').read_bytes()
        origin_sha = hashlib.sha256(origin_raw).hexdigest()
        original = json.loads(origin_raw)
        recovered = (origin/'candidate.bundle').read_bytes()
        metadata = original['candidate']
        if (original.get('phase') != 'candidate_recovered' or original.get('all_vms_stopped') is not True
                or original.get('validation_dispatch_sha256') != dispatch_sha
                or metadata.get('commit') != '88e295f7f71a4241a3ca65e99ac5aebcec903d20'
                or metadata.get('bundle_sha256') != '9b89d4a565bb650d66962cf1b5af7efe2219c3ab90d455412170f446aafb2406'
                or hashlib.sha256(recovered).hexdigest() != metadata['bundle_sha256']):
            raise RuntimeError('Fixed recovered candidate evidence required')
        packet = prepare_import(packet, recovered, metadata)
    policy.NAME, policy.UUID = 'e-base-validation', '84a0fc99-4cbb-4383-a1df-4c22bbe0d2e6'
    with open('/tmp/e-base-devin-fleet-global.lock', 'r') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        policy.stopped()
        if not any(policy.scoped_deny(r) and r.get('resources') == ['**'] for r in policy.rules()):
            raise RuntimeError('Blanket denial required')
        if any(policy.allowed(h) is not False for h in ('example.com:443','deb.debian.org:443')):
            raise RuntimeError('Network denial not verified')
        prefix = 'stdlib-import-' if import_check else 'stdlib-candidate-'
        work = Path(tempfile.mkdtemp(prefix=prefix, dir=ROOT))
        with (ROOT/(prefix+'v1.reservation')).open('x') as stream:
            json.dump(dict(directory=str(work), manifest_sha256=DIGEST), stream)
            stream.flush()
            os.fsync(stream.fileno())
        _sync_directory(ROOT)
        receipt = dict(schema=1, phase='prepared', image_id=IMAGE, expected=expected,
                       mode='import_check' if import_check else 'build', origin_receipt_sha256=origin_sha,
                       validation_dispatch_sha256=dispatch_sha, published=False, production_accepted=False)
        def save():
            atomic_write_json(work/'receipt.json', receipt)
        save()
        print('evidence='+str(work), flush=True)
        source = 'IMAGE='+repr(IMAGE)+'\nINNER='+repr(INNER)+'\n'+GUEST
        def limit():
            resource.setrlimit(resource.RLIMIT_FSIZE, (24*1024*1024,24*1024*1024))
        guest = None
        try:
            receipt['phase'] = 'running'
            save()
            with (work/'stdout.json').open('xb') as stdout, (work/'stderr.log').open('xb') as stderr:
                result = subprocess.run(SBX+['exec','-i',policy.NAME,'/usr/bin/python3','-I','-c',source],
                    input=packet, stdout=stdout, stderr=stderr, timeout=180, preexec_fn=limit)
                stdout.flush()
                os.fsync(stdout.fileno())
            if result.returncode:
                raise RuntimeError('Candidate VM command failed; inspect reserved attempt')
            guest = json.loads((work/'stdout.json').read_bytes())
        finally:
            for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
                signal.signal(sig, signal.SIG_IGN)
            receipt['phase'] = 'inspection_required'
            try:
                policy.run('stop',policy.NAME)
                policy.stopped()
                receipt['all_vms_stopped'] = True
            except BaseException as error:
                receipt.update(all_vms_stopped=False, cleanup_error_type=type(error).__name__)
                raise
            finally:
                save()
        if not guest or guest.get('passed') is not True or guest.get('container_stopped') is not True:
            raise RuntimeError('Candidate build failed; inspect reserved attempt')
        candidate = guest.pop('candidate')
        bundle = base64.b64decode(candidate['bundle'], validate=True)
        metadata = candidate['metadata']
        if import_check and (metadata.get('import_verified') is not True
                or metadata.get('verified_file_count') != expected['file_count']
                or metadata.get('checked_out') is not False or metadata.get('source_executed') is not False
                or metadata.get('commit') != '88e295f7f71a4241a3ca65e99ac5aebcec903d20'
                or metadata.get('bundle_sha256') != '9b89d4a565bb650d66962cf1b5af7efe2219c3ab90d455412170f446aafb2406'):
            raise RuntimeError('Import result mismatch')
        if (guest.get('image_id') != IMAGE or metadata.get('parent') != expected['base']
                or guest.get('boundary', {}).get('observations_verified') is not True
                or guest.get('boundary', {}).get('full_isolation_accepted') is not False
                or not isinstance(metadata.get('commit'), str)
                or re.fullmatch('[0-9a-f]{40}', metadata['commit']) is None
                or metadata.get('production_accepted') is not False or metadata.get('published') is not False
                or metadata.get('tree') != expected['tree'] or metadata.get('manifest_sha256') != DIGEST
                or len(bundle) > 16*1024*1024 or len(bundle) != metadata.get('bundle_bytes')
                or hashlib.sha256(bundle).hexdigest() != metadata.get('bundle_sha256')):
            raise RuntimeError('Candidate result binding mismatch')
        with (work/'candidate.bundle').open('xb') as stream:
            stream.write(bundle)
            stream.flush()
            os.fsync(stream.fileno())
        _sync_directory(work)
        receipt.update(phase='import_verified' if import_check else 'candidate_recovered',
                       candidate=metadata, container_evidence=guest)
        save()
        print(json.dumps(receipt), flush=True)


if __name__ == '__main__':
    import sys
    if sys.argv[1:] == ['--verify-import']:
        main(import_check=True)
    elif not sys.argv[1:]:
        main()
    else:
        raise ValueError('Unknown fixed action')
