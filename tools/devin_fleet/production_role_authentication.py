"""Bind ten successful fixed-model receipts to one prepared candidate."""
import hashlib
import json
import os
from pathlib import Path

from durable import _sync_directory
from managed_cli_guard import require_managed_namespace
from process_control import global_lock_held
from production_registration_candidate import ROOT
from production_registration_prepare import RUN, inspect as inspect_candidate
from sandbox_runtime import ROLES
from validation_dispatch_receipt import _pairs
from validation_snapshot_input import _directory, _file

EVIDENCE = ROOT/'production-role-authentication-v1'
MANIFEST = EVIDENCE/'manifest.json'
HOSTS = ['api.devin.ai:443','app.devin.ai:443','server.codeium.com:443']


def _successful_receipt(raw, candidate):
    value=json.loads(raw,object_pairs_hook=_pairs)
    outer={'schema','phase','sandbox_id','sandbox_name','auth_hosts','original_deny_id',
           'model_executed','terminal_recorded','temporary_deny_ids','smoke',
           'network_denied_after','all_vms_stopped','cleanup_errors'}
    smoke_keys={'model_executed','raw_output_suppressed','phase','returncode',
                'response_marker_seen','exact_model_verified','no_tool_calls','passed'}
    if (type(value) is not dict or set(value)!=outer or value.get('schema')!=1
            or value.get('phase')!='closed' or value.get('model_executed')!='attempted'
            or value.get('terminal_recorded') is not False
            or value.get('network_denied_after') is not True
            or value.get('all_vms_stopped') is not True or value.get('cleanup_errors')!=[]
            or value.get('auth_hosts')!=HOSTS
            or type(value.get('original_deny_id')) is not str
            or not value['original_deny_id']
            or type(value.get('temporary_deny_ids')) is not list
            or any(type(item) is not str or not item for item in value['temporary_deny_ids'])):
        raise ValueError('Invalid fixed-model outer receipt')
    smoke=value['smoke']
    expected={'model_executed':'attempted','raw_output_suppressed':True,'phase':'finished',
              'returncode':0,'response_marker_seen':True,'exact_model_verified':True,
              'no_tool_calls':True,'passed':True}
    if type(smoke) is not dict or set(smoke)!=smoke_keys or smoke!=expected:
        raise ValueError('Fixed-model success required')
    matches=[role for role,entry in candidate['roles'].items()
             if entry['id']==value['sandbox_id'] and entry['name']==value['sandbox_name']]
    if len(matches)!=1:
        raise ValueError('Receipt is not bound to one candidate role')
    return matches[0],'fixed_smoke_receipt'


def _legacy_machine_receipt(raw,candidate):
    value=json.loads(raw,object_pairs_hook=_pairs)
    outer={'schema','phase','sandbox_id','sandbox_name','auth_hosts','original_deny_id',
           'model_executed','terminal_recorded','smoke_evidence',
           'network_denied_after','all_vms_stopped','cleanup_errors'}
    if (type(value) is not dict or set(value)!=outer or type(value.get('schema')) is not int
            or value['schema']!=1 or value.get('phase')!='closed'
            or value.get('model_executed') is not False
            or value.get('terminal_recorded') is not False
            or value.get('network_denied_after') is not True
            or value.get('all_vms_stopped') is not True or value.get('cleanup_errors')!=[]
            or value.get('auth_hosts')!=HOSTS
            or value.get('sandbox_id')!=candidate['roles']['machine']['id']
            or value.get('sandbox_name')!=candidate['roles']['machine']['name']):
        raise ValueError('Invalid legacy machine evidence outer receipt')
    evidence=value['smoke_evidence']
    rows=evidence.get('smoke_export_metadata') if type(evidence) is dict \
        and set(evidence)=={'smoke_export_metadata'} else None
    if type(rows) is not list or len(rows)!=1:
        raise ValueError('One legacy machine export required')
    row=rows[0]
    keys={'agent_model_names','agent_steps','export_sha256',
          'exact_model_verified','no_tool_calls'}
    if (type(row) is not dict or set(row)!=keys
            or row.get('agent_model_names')!=['SWE-2 High']
            or type(row.get('agent_steps')) is not int or row['agent_steps']!=1
            or type(row.get('export_sha256')) is not str
            or len(row['export_sha256'])!=64
            or any(ch not in '0123456789abcdef' for ch in row['export_sha256'])
            or row.get('exact_model_verified') is not True
            or row.get('no_tool_calls') is not True):
        raise ValueError('Invalid legacy machine export metadata')
    return 'machine','legacy_export_attestation'


def _receipt_inventory(candidate):
    _directory(ROOT)
    names=[name for name in os.listdir(ROOT) if name.startswith('interactive-auth-')]
    if not names or len(names)>256:
        raise ValueError('Bounded interactive receipt inventory required')
    found={role:[] for role in ROLES}
    for name in names:
        directory=ROOT/name
        try:
            _directory(directory)
            raw=_file(directory/'receipt.json',65536)
            try:
                role,kind=_successful_receipt(raw,candidate)
            except (ValueError,KeyError,TypeError,json.JSONDecodeError):
                role,kind=_legacy_machine_receipt(raw,candidate)
        except (FileNotFoundError,NotADirectoryError,ValueError,KeyError,TypeError,
                json.JSONDecodeError):
            continue
        found[role].append({'path':str(directory/'receipt.json'),'evidence_kind':kind,
                            'sha256':hashlib.sha256(raw).hexdigest()})
    counts={role:len(found[role]) for role in sorted(ROLES)}
    if any(counts[role]!=1 for role in ROLES):
        raise ValueError('Exactly one successful fixed-model receipt per role required: '
                         +json.dumps(counts,sort_keys=True,separators=(',',':')))
    return {role:found[role][0] for role in sorted(ROLES)}


def _candidate():
    prepared=inspect_candidate()
    raw=_file(RUN/'candidate.json',65536)
    candidate=json.loads(raw,object_pairs_hook=_pairs)
    if hashlib.sha256(raw).hexdigest()!=prepared['candidate_sha256']:
        raise ValueError('Prepared candidate digest mismatch')
    return prepared,candidate


def prepare():
    require_managed_namespace()
    if not global_lock_held('/tmp/e-base-devin-fleet-global.lock'):
        raise ValueError('Global controller lock required')
    prepared,candidate=_candidate()
    receipts=_receipt_inventory(candidate)
    roles={role:{'sandbox_id':candidate['roles'][role]['id'],
                 'sandbox_name':candidate['roles'][role]['name'],
                 'image_digest':candidate['roles'][role]['image_digest'],
                 'evidence_kind':receipts[role]['evidence_kind'],
                 'receipt_path':receipts[role]['path'],
                 'receipt_sha256':receipts[role]['sha256']}
           for role in sorted(ROLES)}
    value={'schema':1,'phase':'complete','candidate_sha256':prepared['candidate_sha256'],
           'migration_epoch':candidate['migration_epoch'],'role_count':len(roles),
           'roles':roles,'credentials_copied':False,'raw_output_exported':False,
           'model_executed':False,'automatic_resume':False,'activated':False}
    EVIDENCE.mkdir(mode=0o700)
    raw=(json.dumps(value,sort_keys=True,separators=(',',':'))+'\n').encode()
    fd=os.open(MANIFEST,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(fd,'wb') as stream:
        stream.write(raw);stream.flush();os.fsync(stream.fileno())
    _sync_directory(EVIDENCE);_sync_directory(ROOT)
    return inspect()


def inspect(candidate=None, candidate_sha256=None):
    require_managed_namespace()
    prepared,loaded=_candidate()
    candidate=loaded if candidate is None else candidate
    candidate_sha256=prepared['candidate_sha256'] if candidate_sha256 is None else candidate_sha256
    _directory(EVIDENCE)
    if set(os.listdir(EVIDENCE))!={'manifest.json'}:
        raise ValueError('Exact role authentication evidence required')
    value=json.loads(_file(MANIFEST,131072),object_pairs_hook=_pairs)
    keys={'schema','phase','candidate_sha256','migration_epoch','role_count','roles',
          'credentials_copied','raw_output_exported','model_executed',
          'automatic_resume','activated'}
    if (type(value) is not dict or set(value)!=keys or value.get('schema')!=1
            or value.get('phase')!='complete'
            or value.get('candidate_sha256')!=candidate_sha256
            or value.get('migration_epoch')!=candidate.get('migration_epoch')
            or value.get('role_count')!=len(ROLES)
            or set(value.get('roles',{}))!=set(ROLES)
            or value.get('credentials_copied') is not False
            or value.get('raw_output_exported') is not False
            or value.get('model_executed') is not False
            or value.get('automatic_resume') is not False
            or value.get('activated') is not False):
        raise ValueError('Invalid role authentication manifest')
    entry_keys={'sandbox_id','sandbox_name','image_digest','evidence_kind',
                'receipt_path','receipt_sha256'}
    for role in ROLES:
        entry=value['roles'][role]
        expected=candidate['roles'][role]
        if (type(entry) is not dict or set(entry)!=entry_keys
                or entry['sandbox_id']!=expected['id']
                or entry['sandbox_name']!=expected['name']
                or entry['image_digest']!=expected['image_digest']
                or entry['evidence_kind'] not in (
                    'fixed_smoke_receipt','legacy_export_attestation')
                or (role!='machine' and entry['evidence_kind']!='fixed_smoke_receipt')):
            raise ValueError('Role authentication identity mismatch')
        path=Path(entry['receipt_path'])
        if path.parent.parent!=ROOT or not path.parent.name.startswith('interactive-auth-') or path.name!='receipt.json':
            raise ValueError('Role receipt path outside controller inventory')
        raw=_file(path,65536)
        if hashlib.sha256(raw).hexdigest()!=entry['receipt_sha256']:
            raise ValueError('Role receipt changed')
        try:
            observed_role,kind=_successful_receipt(raw,candidate)
        except (ValueError,KeyError,TypeError,json.JSONDecodeError):
            observed_role,kind=_legacy_machine_receipt(raw,candidate)
        if observed_role!=role or kind!=entry['evidence_kind']:
            raise ValueError('Role receipt validation failed')
    kinds={role:value['roles'][role]['evidence_kind'] for role in sorted(ROLES)}
    return {'verified':True,'role_count':len(ROLES),'evidence_kinds':kinds,
            'candidate_sha256':candidate_sha256,'migration_epoch':candidate['migration_epoch'],
            'manifest_sha256':hashlib.sha256(_file(MANIFEST,131072)).hexdigest()}
