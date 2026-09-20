"""Pure evidence binding. The trusted supervisor must enforce reservation/lifetime.

Never treat a caller-created completion dictionary as proof of live execution.
No registration, VM, model, file I/O, or automatic retry is performed here.
"""
import hashlib
import json
import re
from mcp_probe_audit import summarize_nonce_audit
from mcp_denial_evidence import summarize
from validation_dispatch_receipt import _pairs

ARTIFACTS = frozenset(('fixture.py','audit_support.py','runner.py','config.json',
                        '.devin/mcp_config.json','prompt.txt','.git/HEAD','.git/config','inherited-mcp.sha256'))


def digest(raw):
    if type(raw) is not bytes or not 0<len(raw)<=1048576:
        raise ValueError('Bounded evidence bytes required')
    return hashlib.sha256(raw).hexdigest()


def bind_probe(reservation, completion, *, inputs_before, inputs_after, audit_raw, export_raw):
    if type(reservation) is not dict or set(reservation)!={'schema','nonce','phase','input_sha256','audit_identity','previous_sessions'}:
        raise ValueError('Fixed reservation required')
    if type(reservation['schema']) is not int or reservation['schema']!=1 or reservation['phase']!='reserved':
        raise ValueError('Durable reservation schema required')
    nonce=reservation['nonce']
    if type(nonce) is not str or re.fullmatch('[0-9a-f]{32}',nonce) is None:
        raise ValueError('Reserved nonce required')
    expected=reservation['input_sha256']
    if type(expected) is not dict or set(expected)!=ARTIFACTS:
        raise ValueError('Exact prepared inputs required')
    for observed in (inputs_before,inputs_after):
        if type(observed) is not dict or set(observed)!=ARTIFACTS:
            raise ValueError('Complete before/after inputs required')
        if {key:digest(raw) for key,raw in observed.items()}!=expected:
            raise ValueError('Prepared input changed')
    if type(completion) is not dict or set(completion)!={'nonce','returncode','processes_stopped','audit_identity','audit_sha256','export_sha256','resume_used'}:
        raise ValueError('Fixed stopped completion required')
    if (completion['nonce']!=nonce or type(completion['returncode']) is not int
            or completion['returncode']!=0 or completion['processes_stopped'] is not True
            or completion['resume_used'] is not False):
        raise ValueError('Fresh completed CLI process required')
    identity=reservation['audit_identity']
    if (type(identity) is not list or len(identity)!=2
            or any(type(n) is not int or n<0 for n in identity)
            or type(completion['audit_identity']) is not list
            or any(type(n) is not int for n in completion['audit_identity'])
            or completion['audit_identity']!=identity):
        raise ValueError('Audit inode identity changed')
    if completion['audit_sha256']!=digest(audit_raw) or completion['export_sha256']!=digest(export_raw):
        raise ValueError('Final evidence hash changed')
    audit=summarize_nonce_audit(audit_raw,nonce)
    payload=json.loads(export_raw,object_pairs_hook=_pairs)
    if type(payload) is not dict:
        raise ValueError('Export object required')
    session=payload.get('session_id')
    previous=reservation['previous_sessions']
    if (type(previous) is not list or len(previous)>4096
            or any(type(s) is not str or not s or len(s)>128 for s in previous)
            or type(session) is not str or not 1<=len(session)<=128
            or any(ord(c)<33 or ord(c)>126 for c in session) or session in previous):
        raise ValueError('New bounded export session required')
    result=summarize(payload,discovery_verified=(audit['discovery_sequence_observed']
                                               and audit['initialization_count']==1))
    result['permission_denial_observed']=result.pop('passed') and audit['tool_call_count']==0
    result.update(passed=False, evidence_bound=True, live_execution_verified=False,
                  attempt_nonce=nonce, session_id=session,
                  audit_sha256=completion['audit_sha256'], export_sha256=completion['export_sha256'])
    return result
