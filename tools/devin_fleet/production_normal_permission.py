"""Bind a bounded Normal-mode write turn and its independent inspection."""
import hashlib
import json
import os
from pathlib import Path

from durable import _sync_directory
from managed_cli_guard import require_managed_namespace
from process_control import global_lock_held
from production_registration_candidate import ROOT
from production_registration_prepare import RUN,inspect as inspect_candidate
from validation_dispatch_receipt import _pairs
from validation_snapshot_input import _directory,_file

EVIDENCE=ROOT/'production-normal-permission-v1'
MANIFEST=EVIDENCE/'manifest.json'
HOSTS=['api.devin.ai:443','app.devin.ai:443','server.codeium.com:443']


def _outer(value,candidate,keys):
    machine=candidate['roles']['machine']
    common={'schema','phase','sandbox_id','sandbox_name','auth_hosts','original_deny_id',
            'model_executed','terminal_recorded','network_denied_after',
            'all_vms_stopped','cleanup_errors'}
    if (type(value) is not dict or set(value)!=common|keys
            or type(value.get('schema')) is not int or value['schema']!=1
            or value.get('phase')!='closed' or value.get('terminal_recorded') is not False
            or value.get('network_denied_after') is not True
            or value.get('all_vms_stopped') is not True or value.get('cleanup_errors')!=[]
            or value.get('auth_hosts')!=HOSTS or value.get('sandbox_id')!=machine['id']
            or value.get('sandbox_name')!=machine['name']):
        raise ValueError('Invalid Normal permission outer receipt')


def _execution(raw,candidate):
    value=json.loads(raw,object_pairs_hook=_pairs)
    _outer(value,candidate,{'temporary_deny_ids','smoke'})
    expected={'exact_model_verified':True,'file_write_verified':True,
        'model_executed':'attempted','no_tool_calls':False,'passed':True,
        'phase':'finished','production_admitted':False,'raw_output_suppressed':True,
        'response_marker_seen':True,'returncode':0,'shell_denial_verified':False}
    if (value.get('model_executed')!='attempted'
            or type(value.get('temporary_deny_ids')) is not list
            or type(value.get('smoke')) is not dict or value['smoke']!=expected
            or type(value['smoke']['returncode']) is not int):
        raise ValueError('Invalid Normal permission execution')
    return 'normal_write_execution'


def _inspection(raw,candidate):
    value=json.loads(raw,object_pairs_hook=_pairs)
    _outer(value,candidate,{'smoke_evidence'})
    rows=value.get('smoke_evidence',{}).get('file_probe_evidence') \
        if type(value.get('smoke_evidence')) is dict else None
    wrapper=value.get('smoke_evidence')
    if (value.get('model_executed') is not False
            or set(wrapper or {})!={'file_probe_evidence','model_executed','raw_output_suppressed'}
            or wrapper.get('model_executed') is not False
            or wrapper.get('raw_output_suppressed') is not True
            or type(rows) is not list or len(rows)!=1):
        raise ValueError('Invalid Normal permission inspection wrapper')
    row=rows[0]
    expected={'all_calls_expected_write':True,'exact_model_verified':True,
        'expected_write_call_count':1,'file_write_verified':True,
        'production_admitted':False,'shell_denial_verified':False,'tool_call_count':1}
    if (type(row) is not dict or set(row)!=set(expected)|{'export_sha256'}
            or any(type(row[key]) is not type(expected[key]) or row[key]!=expected[key]
                   for key in expected)
            or type(row.get('export_sha256')) is not str or len(row['export_sha256'])!=64
            or any(ch not in '0123456789abcdef' for ch in row['export_sha256'])):
        raise ValueError('Invalid Normal permission inspection')
    return 'normal_write_inspection'


def _candidate():
    prepared=inspect_candidate()
    raw=_file(RUN/'candidate.json',65536)
    candidate=json.loads(raw,object_pairs_hook=_pairs)
    if hashlib.sha256(raw).hexdigest()!=prepared['candidate_sha256']:
        raise ValueError('Prepared candidate digest mismatch')
    return prepared,candidate


def _inventory(candidate):
    names=[name for name in os.listdir(ROOT) if name.startswith('interactive-auth-')]
    if not names or len(names)>256:raise ValueError('Bounded receipt inventory required')
    found={'normal_write_execution':[],'normal_write_inspection':[]}
    for name in names:
        path=ROOT/name/'receipt.json'
        try:
            _directory(path.parent);raw=_file(path,65536)
        except (FileNotFoundError,NotADirectoryError,ValueError):
            continue
        for validator in (_execution,_inspection):
            try:kind=validator(raw,candidate)
            except (ValueError,KeyError,TypeError,json.JSONDecodeError):continue
            found[kind].append({'path':str(path),'sha256':hashlib.sha256(raw).hexdigest()})
    if any(len(rows)!=1 for rows in found.values()):
        raise ValueError('Exactly one execution and inspection receipt required')
    return {kind:rows[0] for kind,rows in found.items()}


def prepare():
    require_managed_namespace()
    if not global_lock_held('/tmp/e-base-devin-fleet-global.lock'):
        raise ValueError('Global controller lock required')
    prepared,candidate=_candidate();receipts=_inventory(candidate)
    machine=candidate['roles']['machine']
    value={'schema':1,'phase':'complete','candidate_sha256':prepared['candidate_sha256'],
        'migration_epoch':candidate['migration_epoch'],'sandbox_id':machine['id'],
        'sandbox_name':machine['name'],'image_digest':machine['image_digest'],
        'receipts':receipts,'permission_mode':'normal','tool_call_count':1,
        'expected_write_call_count':1,'file_write_verified':True,
        'production_admitted':False,'model_executed':False,'automatic_resume':False,
        'activated':False}
    EVIDENCE.mkdir(mode=0o700);raw=(json.dumps(value,sort_keys=True,separators=(',',':'))+'\n').encode()
    fd=os.open(MANIFEST,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(fd,'wb') as stream:
        stream.write(raw);stream.flush();os.fsync(stream.fileno())
    _sync_directory(EVIDENCE);_sync_directory(ROOT)
    return inspect()


def inspect(candidate=None,candidate_sha256=None):
    require_managed_namespace()
    prepared,loaded=_candidate();candidate=loaded if candidate is None else candidate
    candidate_sha256=prepared['candidate_sha256'] if candidate_sha256 is None else candidate_sha256
    _directory(EVIDENCE)
    if set(os.listdir(EVIDENCE))!={'manifest.json'}:
        raise ValueError('Exact Normal permission evidence required')
    value=json.loads(_file(MANIFEST,65536),object_pairs_hook=_pairs)
    keys={'schema','phase','candidate_sha256','migration_epoch','sandbox_id','sandbox_name',
          'image_digest','receipts','permission_mode','tool_call_count',
          'expected_write_call_count','file_write_verified','production_admitted',
          'model_executed','automatic_resume','activated'}
    machine=candidate['roles']['machine']
    if (type(value) is not dict or set(value)!=keys or value.get('schema')!=1
            or value.get('phase')!='complete' or value.get('candidate_sha256')!=candidate_sha256
            or value.get('migration_epoch')!=candidate['migration_epoch']
            or value.get('sandbox_id')!=machine['id'] or value.get('sandbox_name')!=machine['name']
            or value.get('image_digest')!=machine['image_digest']
            or value.get('permission_mode')!='normal'
            or type(value.get('tool_call_count')) is not int or value['tool_call_count']!=1
            or type(value.get('expected_write_call_count')) is not int
            or value['expected_write_call_count']!=1 or value.get('file_write_verified') is not True
            or value.get('production_admitted') is not False
            or value.get('model_executed') is not False
            or value.get('automatic_resume') is not False or value.get('activated') is not False
            or set(value.get('receipts',{}))!={'normal_write_execution','normal_write_inspection'}):
        raise ValueError('Invalid Normal permission manifest')
    validators={'normal_write_execution':_execution,'normal_write_inspection':_inspection}
    for kind,validator in validators.items():
        entry=value['receipts'][kind]
        if type(entry) is not dict or set(entry)!={'path','sha256'}:
            raise ValueError('Invalid Normal permission receipt binding')
        path=Path(entry['path'])
        if path.parent.parent!=ROOT or not path.parent.name.startswith('interactive-auth-') \
                or path.name!='receipt.json':
            raise ValueError('Normal permission receipt outside controller inventory')
        raw=_file(path,65536)
        if hashlib.sha256(raw).hexdigest()!=entry['sha256'] or validator(raw,candidate)!=kind:
            raise ValueError('Normal permission receipt changed')
    return {'verified':True,'permission_mode':'normal','tool_call_count':1,
        'expected_write_call_count':1,'file_write_verified':True,
        'production_admitted':False,'manifest_sha256':hashlib.sha256(
            _file(MANIFEST,65536)).hexdigest()}
