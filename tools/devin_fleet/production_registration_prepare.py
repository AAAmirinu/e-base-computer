"""One-shot durable production candidate preparation; never activates registry."""
import hashlib
import json
import os
from pathlib import Path
import uuid

from durable import _sync_directory
from managed_cli_guard import require_managed_namespace
from process_control import global_lock_held
from production_registration_candidate import compose, validate, ROOT
from validation_dispatch_receipt import _pairs
from validation_snapshot_input import _directory, _file

RUN = ROOT/'production-registration-preparation-v1'


def _exclusive(path, raw):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(fd,'wb') as stream:
        stream.write(raw);stream.flush();os.fsync(stream.fileno())
    _sync_directory(path.parent)


def prepare():
    require_managed_namespace()
    if not global_lock_held('/tmp/e-base-devin-fleet-global.lock'):
        raise ValueError('Global controller lock required')
    _directory(ROOT)
    source_path=ROOT/'sandbox-registry.json'
    before=source_path.stat()
    source_raw=_file(source_path,65536)
    source=json.loads(source_raw,object_pairs_hook=_pairs)
    RUN.mkdir(mode=0o700)
    _sync_directory(ROOT)
    status={'schema':1,'phase':'preparing','automatic_resume':False,'activated':False}
    _exclusive(RUN/'status.json',(json.dumps(status,sort_keys=True,separators=(',',':'))+'\n').encode())
    root_identity=uuid.uuid4().hex
    epoch=str(uuid.uuid4())
    candidate=compose(source,root_identity=root_identity,migration_epoch=epoch)
    production=Path(candidate['controller_root'])
    production.mkdir(mode=0o700)
    _sync_directory(ROOT)
    for name in ('cycles','operations','model-turn-fences'):
        (production/name).mkdir(mode=0o700)
    for path in (production/'cycles',production/'operations',production/'model-turn-fences',production):
        _sync_directory(path)
    candidate_raw=(json.dumps(candidate,sort_keys=True,allow_nan=False,separators=(',',':'))+'\n').encode()
    _exclusive(RUN/'source-registry.json',source_raw)
    _exclusive(RUN/'candidate.json',candidate_raw)
    after=source_path.stat()
    stamp=lambda value:(value.st_dev,value.st_ino,value.st_mode,value.st_uid,value.st_nlink,value.st_size)
    if _file(source_path,65536)!=source_raw or stamp(before)!=stamp(after):
        raise ValueError('Active registry changed during preparation')
    receipt=dict(status,phase='complete',candidate_sha256=hashlib.sha256(candidate_raw).hexdigest(),
        source_sha256=hashlib.sha256(source_raw).hexdigest(),controller_root=str(production),
        migration_epoch=epoch)
    _exclusive(RUN/'commit.json',(json.dumps(receipt,sort_keys=True,separators=(',',':'))+'\n').encode())
    return inspect()


def inspect():
    require_managed_namespace()
    _directory(ROOT);_directory(RUN)
    if set(os.listdir(RUN))!={'status.json','commit.json','source-registry.json','candidate.json'}:
        raise ValueError('Exact preparation files required')
    status=json.loads(_file(RUN/'status.json',65536),object_pairs_hook=_pairs)
    receipt=json.loads(_file(RUN/'commit.json',65536),object_pairs_hook=_pairs)
    source_raw=_file(RUN/'source-registry.json',65536)
    candidate_raw=_file(RUN/'candidate.json',65536)
    candidate=json.loads(candidate_raw,object_pairs_hook=_pairs)
    source=json.loads(source_raw,object_pairs_hook=_pairs)
    if (status!={'schema':1,'phase':'preparing','automatic_resume':False,'activated':False}
            or type(receipt) is not dict or receipt.get('phase')!='complete'
            or receipt.get('automatic_resume') is not False or receipt.get('activated') is not False
            or receipt.get('candidate_sha256')!=hashlib.sha256(candidate_raw).hexdigest()
            or receipt.get('source_sha256')!=hashlib.sha256(source_raw).hexdigest()
            or receipt.get('controller_root')!=candidate.get('controller_root')
            or receipt.get('migration_epoch')!=candidate.get('migration_epoch')):
        raise ValueError('Incomplete production candidate preparation')
    expected=compose(source,root_identity=Path(candidate['controller_root']).name.removeprefix('production-'),
                     migration_epoch=candidate['migration_epoch'])
    if expected!=candidate or validate(candidate) is not candidate:
        raise ValueError('Candidate reconstruction mismatch')
    production=Path(candidate['controller_root']);_directory(production)
    if set(os.listdir(production))!={'cycles','operations','model-turn-fences'}:
        raise ValueError('Prepared production root changed')
    for name in ('cycles','operations','model-turn-fences'):
        path=production/name;_directory(path)
        if os.listdir(path):raise ValueError('Prepared production directory not empty')
    if _file(ROOT/'sandbox-registry.json',65536)!=source_raw:
        raise ValueError('Active registry differs from preparation source')
    return {'prepared':True,'activated':False,'automatic_resume':False,
            'candidate_sha256':receipt['candidate_sha256'],'source_sha256':receipt['source_sha256'],
            'controller_root':receipt['controller_root'],'migration_epoch':receipt['migration_epoch']}
