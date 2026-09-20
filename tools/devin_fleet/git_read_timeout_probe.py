"""Fixed synthetic blocked-Git probe; real controller timeout stops validator VM."""
import fcntl
import json
from pathlib import Path

from durable import atomic_write_json, _sync_directory
from managed_cli_guard import require_managed_namespace
from sandbox_control import SandboxController, SandboxFenced
from sandbox_repository import _GUEST_CODE
from validation_snapshot_dispatch import inventory, UUID
import interactive_machine_auth as policy

ROOT = Path('/home/fleet/controller-validation')
WORK = ROOT/'git-read-timeout-v1'
IMAGE = 'sha256:cee9fe9272c17a34c0b1620485843ff67431dcc18d2e0f7380581fe28f5aeaf4'
INNER = r'''
import json, os, pathlib, subprocess, sys, time
if os.getuid()!=65532 or not pathlib.Path('/.dockerenv').is_file():
    raise RuntimeError('Credential-free container required')
root=pathlib.Path('/work/blocked-git')
root.mkdir()
subprocess.run(['/usr/bin/git','init',str(root)],check=True,capture_output=True,timeout=10)
(root/'.git/config').rename(root/'.git/config.saved')
os.mkfifo(root/'.git/config')
request=dict(operation='git_read',root=str(root),limit=65536,args=['rev-parse','HEAD'])
child=subprocess.Popen([sys.executable,'-I','-c',REPOSITORY_CODE,'UNEXPECTED_RESULT:',json.dumps(request)],
    env={'PATH':'/usr/bin:/bin','HOME':'/home/agent','LC_ALL':'C.UTF-8'},stdin=subprocess.DEVNULL)
deadline=time.monotonic()+5
while time.monotonic()<deadline:
    if child.poll() is not None:
        raise RuntimeError('Repository command did not block')
    children=pathlib.Path('/proc/'+str(child.pid)+'/task/'+str(child.pid)+'/children').read_text().split()
    for pid in children:
        proc=pathlib.Path('/proc')/pid
        try:
            args=(proc/'cmdline').read_bytes().split(b'\0')
            state=(proc/'stat').read_text().rsplit(')',1)[1].split()
        except FileNotFoundError:
            continue
        if (args[:4]==[b'/usr/bin/git',b'--no-pager',b'config',b'--null'] and state[0]=='S'
                and os.readlink(proc/'exe')=='/usr/bin/git'):
            print('GIT_READ_BLOCKED:'+json.dumps(dict(git_pid=int(pid),start_ticks=state[19],
                container_id=CONTAINER_ID,synthetic_only=True)),flush=True)
            time.sleep(300)
            raise RuntimeError('Outer timeout did not stop container')
    time.sleep(.05)
raise RuntimeError('No blocked Git subprocess observed')
'''
GUEST = r'''
import json, subprocess, sys, uuid
sys.path.insert(0,'/tmp')
from sandbox_validation_container import admit_image,create_arguments,verify_created_container,ENV
from validation_container_smoke import run
admit_image(json.loads(run(['docker','image','inspect',IMAGE]))[0])
operation=uuid.uuid4().hex
container=run(create_arguments(IMAGE,operation)).strip()
verify_created_container(json.loads(run(['docker','inspect',container]))[0],IMAGE,operation)
run(['docker','start',container])
# Intentionally no guest-side stop on this path: the real outer controller must
# stop the complete VM and descendants. Its finally and the root launcher own cleanup.
source='CONTAINER_ID='+repr(container)+'\nREPOSITORY_CODE='+repr(REPOSITORY_CODE)+'\n'+INNER
result=subprocess.run(['docker','exec',container,'/usr/bin/env','-i',*ENV,
    '/usr/local/bin/python3','-I','-c',source],stdin=subprocess.DEVNULL)
raise RuntimeError('Expected outer controller timeout')
'''


def main():
    require_managed_namespace()
    with open('/tmp/e-base-devin-fleet-global.lock','r') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        rows,_=inventory()
        if len(rows)!=11 or any(row['status']!='stopped' for row in rows):
            raise RuntimeError('Eleven stopped VMs required')
        policy.NAME,policy.UUID='e-base-validation',UUID
        if (not any(policy.scoped_deny(r) and r.get('resources')==['**'] for r in policy.rules())
                or any(policy.allowed(host) is not False for host in ('example.com:443','deb.debian.org:443'))):
            raise RuntimeError('Validation network denial required')
        WORK.mkdir(mode=0o700)
        _sync_directory(ROOT)
        receipt=dict(schema=1,phase='prepared',model_executed=False,project_source_executed=False,
                     production_accepted=False,automatic_resume=False,all_vms_stopped=False)
        def save():
            atomic_write_json(WORK/'receipt.json',receipt)
        save()
        controller=SandboxController('e-base-validation',WORK/'STOP',sandbox_id=UUID)
        try:
            controller.resume()
            source='IMAGE='+repr(IMAGE)+'\nINNER='+repr(INNER)+'\nREPOSITORY_CODE='+repr(_GUEST_CODE)+'\n'+GUEST
            try:
                controller.execute(['/usr/bin/python3','-I','-c',source],cwd='/',
                    log_path=WORK/'blocked.log',timeout=30,max_log_bytes=65536)
            except SandboxFenced as error:
                if str(error) != 'Sandbox execution timed out':
                    raise RuntimeError('Fence was not caused by execution timeout') from error
                receipt['execution_fenced']=True
                receipt['timeout_observed']=True
            else:
                raise RuntimeError('Expected controller timeout fence')
            raw=(WORK/'blocked.log').read_bytes()
            prefix=b'GIT_READ_BLOCKED:'
            markers=[json.loads(line[len(prefix):]) for line in raw.splitlines() if line.startswith(prefix)]
            if len(markers)!=1 or not controller.fenced or not (WORK/'STOP').is_file():
                raise RuntimeError('Blocked Git and persistent fence not established')
            receipt['blocked_git']=markers[0]
            try:
                controller.execute(['/usr/bin/true'],cwd='/',log_path=WORK/'forbidden-retry.log',timeout=5)
            except SandboxFenced:
                if (WORK/'forbidden-retry.log').exists():
                    raise RuntimeError('Fenced retry spawned')
                receipt['retry_rejected_before_spawn']=True
            else:
                raise RuntimeError('Fenced retry admitted')
            receipt['phase']='timeout_stop_verified'
        finally:
            try:
                controller.stop()
                rows,_=inventory()
                if len(rows)!=11 or any(row['status']!='stopped' for row in rows):
                    raise RuntimeError('Final VM stop unverified')
                receipt['all_vms_stopped']=True
            finally:
                save()
        print(json.dumps(dict(evidence=str(WORK),**receipt)),flush=True)


if __name__=='__main__':
    main()
