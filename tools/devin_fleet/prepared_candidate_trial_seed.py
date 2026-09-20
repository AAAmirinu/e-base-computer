"""One-shot exact bundle seed for the inert machine trial repository."""
import base64
import hashlib
import json
import os

from durable import atomic_write_json, _sync_directory
from prepared_candidate_trial_runtime import PreparedCandidateTrialRuntime
from validation_snapshot_input import _file
import prepared_candidate_trial_guards as guards
import prepared_candidate_trial_state as state
import prepared_trial_project as project


GUEST_CODE = r'''
import base64, hashlib, json, os, pathlib, stat, subprocess, sys
request=json.loads(sys.argv[1])
agent=pathlib.Path('/home/agent')
base=agent/'e-base-trials'
binding=base/request['target'].split('/')[-2]
target=pathlib.Path(request['target'])
bundle=binding/'parent-v12.bundle'
for path in (pathlib.Path('/home'),agent):
    if not stat.S_ISDIR(path.lstat().st_mode) or path.is_symlink():
        raise ValueError('Untrusted guest workspace parent')
for path in (base,binding):
    if path.is_symlink() or not path.is_dir():
        raise ValueError('Trusted trial seed parent missing')
if target.parent!=binding or target.name!='machine-v12' or os.path.lexists(target):
    raise ValueError('Unexpected fixed trial target')
raw=base64.b64decode(request['bundle'],validate=True)
if hashlib.sha256(raw).hexdigest()!=request['bundle_sha256']:
    raise ValueError('Trial seed bundle digest mismatch')
fd=os.open(bundle,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
with os.fdopen(fd,'wb') as stream:
    stream.write(raw);stream.flush();os.fsync(stream.fileno())
env={'PATH':'/usr/bin:/bin','HOME':'/nonexistent','LC_ALL':'C',
     'GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':'/dev/null'}
def git(*args):
    return subprocess.check_output(['/usr/bin/git','-c','core.hooksPath=/dev/null',
        '-c','core.fsmonitor=false','-c','core.excludesFile=',*args],
        env=env,stdin=subprocess.DEVNULL,stderr=subprocess.STDOUT)
git('init','--initial-branch=trial',str(target))
git('-C',str(target),'fetch','--no-tags','--no-write-fetch-head',str(bundle),
    'refs/heads/main:refs/fixed-trial/parent')
git('-C',str(target),'checkout','--detach',request['head'])
if git('-C',str(target),'rev-parse','HEAD^{tree}').decode().strip()!=request['tree']:
    raise ValueError('Trial seed tree mismatch')
if git('-C',str(target),'status','--porcelain=v1','-z','--untracked-files=all'):
    raise ValueError('Trial seed checkout not clean')
git('-C',str(target),'fsck','--full')
print('FIXED_TRIAL_SEED_OK '+request['head'])
'''

GUEST_INSPECT_CODE = r'''
import hashlib,json,os,pathlib,stat
root=pathlib.Path('/home/agent/workspace/machine')
def kind(mode):
    if stat.S_ISREG(mode): return 'regular'
    if stat.S_ISDIR(mode): return 'directory'
    if stat.S_ISLNK(mode): return 'symlink'
    return 'other'
result={'exists':os.path.lexists(root),'entries':[]}
if result['exists']:
    info=root.lstat()
    result['root']={'kind':kind(info.st_mode),'uid':info.st_uid,'gid':info.st_gid,
                    'mode':stat.S_IMODE(info.st_mode)}
    if stat.S_ISDIR(info.st_mode) and not root.is_symlink():
        count=0
        for current,dirs,files in os.walk(root,topdown=True,followlinks=False):
            dirs.sort();files.sort()
            base=pathlib.Path(current)
            for name in list(dirs)+list(files):
                count+=1
                if count>256: raise ValueError('Workspace inventory exceeds bound')
                path=base/name
                relative=str(path.relative_to(root))
                meta=path.lstat();entry={'path':relative,'kind':kind(meta.st_mode),
                    'size':meta.st_size,'mode':stat.S_IMODE(meta.st_mode),
                    'uid':meta.st_uid,'gid':meta.st_gid}
                if stat.S_ISREG(meta.st_mode) and meta.st_size<=65536:
                    entry['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
                result['entries'].append(entry)
            dirs[:]=[name for name in dirs if not (base/name).is_symlink()]
print('FIXED_TRIAL_INVENTORY '+json.dumps(result,sort_keys=True,separators=(',',':')))
'''

GUEST_TRIAL_DIAG_CODE = r'''
import json,os,pathlib,stat,subprocess,sys
target=pathlib.Path(sys.argv[1])
env={'PATH':'/usr/bin:/bin','HOME':'/home/agent','LC_ALL':'C.UTF-8',
     'GIT_TERMINAL_PROMPT':'0','GIT_PAGER':'cat'}
def run(*args):
    value=subprocess.run(['/usr/bin/git','--no-pager',*args],cwd=target,env=env,
        stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
    return value.returncode,value.stdout
code,raw=run('config','--null','--list','--no-includes')
config=[]
if code==0:
    for item in raw.rstrip(b'\0').split(b'\0'):
        key,_,value=item.partition(b'\n')
        name=key.decode('ascii','replace')
        row={'key':name}
        if name in ('core.repositoryformatversion','core.filemode','core.bare','core.logallrefupdates'):
            row['value']=value.decode('ascii','replace')
        config.append(row)
head_code,head=run('rev-parse','HEAD')
tree_code,tree=run('rev-parse','HEAD^{tree}')
result={'target_kind':'directory' if target.is_dir() and not target.is_symlink() else 'other',
 'config_code':code,'config':config,
 'head_ok':head_code==0,'head':head.decode().strip() if head_code==0 else None,
 'tree_ok':tree_code==0,'tree':tree.decode().strip() if tree_code==0 else None,
 'inherited_banned_keys':sorted(k for k in os.environ if k.startswith(('GIT_','LD_'))
                                or k in ('XDG_CONFIG_HOME','XDG_CONFIG_DIRS'))}
print('FIXED_TRIAL_DIAG '+json.dumps(result,sort_keys=True,separators=(',',':')))
'''


def seed():
    """Seed v3 at a new candidate-bound path; never touch the existing workspace."""
    registration=state.runtime_registration()
    prepared=project.inspect()
    bundle=_file(project.BUNDLE,16*1024*1024)
    if len(bundle)>512*1024 or hashlib.sha256(bundle).hexdigest()!=prepared['bundle_sha256']:
        raise ValueError('Bounded exact trial bundle required')
    directory=state.CONTROLLER/'seed-v12'
    os.mkdir(directory,0o700)
    _sync_directory(directory.parent)
    receipt={'schema':1,'phase':'prepared','role':'machine','retry':False,
             'resume_available':False,'activated':False,'published':False,
             'bundle_sha256':prepared['bundle_sha256'],'head':prepared['head'],
             'tree':prepared['tree']}
    path=directory/'receipt.json'
    atomic_write_json(path,receipt)
    request={'bundle':base64.b64encode(bundle).decode('ascii'),
             'bundle_sha256':prepared['bundle_sha256'],
             'head':prepared['head'],'tree':prepared['tree'],
             'target':state.trial_guest_root()}
    try:
        with PreparedCandidateTrialRuntime(registration,state.CONTROLLER,capacity=1) as runtime:
            with runtime.role('machine') as repo:
                result=repo.controller.execute(['python3','-I','-c',GUEST_CODE,
                    json.dumps(request,separators=(',',':'))],cwd='/',
                    log_path=directory/'guest.log',timeout=120,
                    max_log_bytes=1024*1024,external_stop=runtime.stop_path)
                if result.returncode:
                    raise RuntimeError('Fixed trial seed guest failed')
                repo.restrict_git_to_model_reads()
                guards._verify_guest_parent(repo,prepared)
        receipt['phase']='complete'
        receipt['all_vms_stopped']=True
        atomic_write_json(path,receipt)
        return receipt
    except BaseException as error:
        receipt.update(phase='inspection_required',error_type=type(error).__name__)
        atomic_write_json(path,receipt)
        raise


def inspect_existing():
    """Collect bounded metadata only; never read file contents into the controller."""
    registration=state.runtime_registration()
    project.inspect()
    directory=state.CONTROLLER/'seed-inspect-v1'
    os.mkdir(directory,0o700)
    _sync_directory(directory.parent)
    receipt={'schema':1,'phase':'prepared','role':'machine','read_only':True,
             'activated':False,'published':False,'cycle_created':False}
    path=directory/'receipt.json'
    atomic_write_json(path,receipt)
    try:
        with SandboxRuntime(registration,state.CONTROLLER,capacity=1) as runtime:
            with runtime.role('machine') as repo:
                result=repo.controller.execute(['python3','-I','-c',GUEST_INSPECT_CODE],
                    cwd='/',log_path=directory/'guest.log',timeout=60,
                    max_log_bytes=256*1024,external_stop=runtime.stop_path)
                if result.returncode:
                    raise RuntimeError('Fixed workspace inspection failed')
        lines=(directory/'guest.log').read_text(encoding='utf-8').splitlines()
        values=[line[len('FIXED_TRIAL_INVENTORY '):] for line in lines
                if line.startswith('FIXED_TRIAL_INVENTORY ')]
        if len(values)!=1:
            raise ValueError('Unique bounded workspace inventory required')
        inventory=json.loads(values[0])
        if type(inventory) is not dict or type(inventory.get('entries')) is not list:
            raise ValueError('Invalid bounded workspace inventory')
        receipt.update(phase='complete',all_vms_stopped=True,inventory=inventory)
        atomic_write_json(path,receipt)
        return receipt
    except BaseException as error:
        receipt.update(phase='inspection_required',error_type=type(error).__name__)
        atomic_write_json(path,receipt)
        raise


def diagnose_seed_v3():
    registration=state.runtime_registration()
    directory=state.CONTROLLER/'seed-v3-diagnostic-v2'
    os.mkdir(directory,0o700);_sync_directory(directory.parent)
    receipt={'schema':1,'phase':'prepared','read_only':True,'activated':False,
             'published':False,'cycle_created':False}
    path=directory/'receipt.json';atomic_write_json(path,receipt)
    try:
        with PreparedCandidateTrialRuntime(registration,state.CONTROLLER,capacity=1) as runtime:
            with runtime.role('machine') as repo:
                result=repo.controller.execute(['python3','-I','-c',GUEST_TRIAL_DIAG_CODE,
                    state.trial_guest_root()],cwd='/',log_path=directory/'guest.log',
                    timeout=60,max_log_bytes=65536,external_stop=runtime.stop_path)
                if result.returncode: raise RuntimeError('Trial seed diagnostic failed')
        lines=(directory/'guest.log').read_text(encoding='utf-8').splitlines()
        values=[x[len('FIXED_TRIAL_DIAG '):] for x in lines if x.startswith('FIXED_TRIAL_DIAG ')]
        if len(values)!=1: raise ValueError('Unique trial diagnostic required')
        receipt.update(phase='complete',all_vms_stopped=True,diagnostic=json.loads(values[0]))
        atomic_write_json(path,receipt);return receipt
    except BaseException as error:
        receipt.update(phase='inspection_required',error_type=type(error).__name__)
        atomic_write_json(path,receipt);raise
