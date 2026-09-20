"""One-shot admission journal for a trusted, live outer supervisor.

A dictionary is not proof of lock, VM, network or session-history checks.
The caller supplying verify is trusted controller code responsible for those
checks in the current lease. There is intentionally no CLI or saved-permit
loader. Production admission is never granted here.
"""
import hashlib
import json
import os
import re
import time
import math

from mcp_probe_reservation import _exclusive_file
from mcp_probe_snapshot import _read, snapshot
from guest_mcp_prepare import validate as validate_prepared

MARKER='supervised-admission.json'
MACHINE='40e32a36-d565-4853-a841-fa3bea9ac648'


def validate_receipt(raw,*,nonce,reservation_raw,work=None,now=None):
    from model_catalog_policy import _unique, _reject_constant
    if type(raw) is not bytes or not 0<len(raw)<=1048576:
        raise ValueError('Bounded supervisor receipt bytes required')
    value=json.loads(raw,object_pairs_hook=_unique,parse_constant=_reject_constant)
    if (type(value) is not dict or set(value)!={'schema','nonce','reservation_sha256','work',
            'machine_vm_id','lease_id','issued_at','expires_at','session_inventory_scope',
            'session_inventory_verified','fresh_attempt_preconditions_verified','previous_sessions'}
            or type(value['schema']) is not int or value['schema']!=2
            or value['nonce']!=nonce or value['reservation_sha256']!=hashlib.sha256(reservation_raw).hexdigest()
            or value['machine_vm_id']!=MACHINE or type(value['lease_id']) is not str
            or re.fullmatch('[0-9a-f]{32}',value['lease_id']) is None
            or type(value['work']) is not str or re.fullmatch('/tmp/e-base-mcp-probe-[a-z0-9_]{8}',value['work']) is None
            or (work is not None and value['work']!=work)
            or type(value['issued_at']) is not int or type(value['expires_at']) is not int
            or not 0<value['issued_at']<value['expires_at']<=value['issued_at']+180
            or (now is not None and not value['issued_at']<=now<value['expires_at'])
            or value['session_inventory_scope']!='current_workdir'
            or value['session_inventory_verified'] is not True
            or value['fresh_attempt_preconditions_verified'] is not True):
        raise ValueError('Current same-attempt supervisor receipt required')
    previous=value['previous_sessions']
    if (type(previous) is not list or len(previous)>4096
            or any(type(s) is not str or not 1<=len(s)<=128 or any(ord(c)<33 or ord(c)>126 for c in s) for s in previous)
            or len(set(previous))!=len(previous)):
        raise ValueError('Bounded distinct workdir session inventory required')
    return value


def require_unused(claim):
    try: os.stat(MARKER,dir_fd=claim,follow_symlinks=False)
    except FileNotFoundError: return
    raise FileExistsError('Supervised probe admission already consumed')


def bind_supervised_probe(reservation_raw,supervision_raw,completion,**evidence):
    """Use verified history without rewriting the immutable original reservation.

    This binds evidence only; it does not prove the outer supervisor executed.
    """
    from model_catalog_policy import _unique, _reject_constant
    from mcp_probe_binding import bind_probe
    if type(reservation_raw) is not bytes or not 0<len(reservation_raw)<=1048576:
        raise ValueError('Bounded original reservation required')
    reservation=json.loads(reservation_raw,object_pairs_hook=_unique,parse_constant=_reject_constant)
    if type(reservation) is not dict: raise ValueError('Reservation object required')
    admitted=validate_receipt(supervision_raw,nonce=reservation.get('nonce'),reservation_raw=reservation_raw)
    original=reservation.get('previous_sessions')
    if (type(original) is not list or len(original)>4096
            or any(type(s) is not str or not 1<=len(s)<=128 for s in original)
            or not set(original)<=set(admitted['previous_sessions'])):
        raise ValueError('Verified inventory must retain all previously known sessions')
    effective=dict(reservation,previous_sessions=admitted['previous_sessions'])
    result=bind_probe(effective,completion,**evidence)
    result['supervision_sha256']=hashlib.sha256(supervision_raw).hexdigest()
    return result


def consume(state,claim,*,nonce,reservation_raw,work,timeout,verify):
    """Persist consumption before any CLI call; never remove on later failure."""
    if not callable(verify): raise ValueError('Live trusted supervisor required')
    if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0<timeout<=180:
        raise ValueError('Bounded supervisor deadline required')
    require_unused(claim)
    if _read(state,'prepare-only',1)[0]!=b'': raise ValueError('Preparation hold changed')
    from model_catalog_policy import _unique, _reject_constant
    prepared=validate_prepared(json.loads(_read(state,'prepared.json',4096)[0],
                                         object_pairs_hook=_unique,parse_constant=_reject_constant))
    if not prepared['prepared']: raise ValueError('Completed preparation required')
    reservation=json.loads(reservation_raw,object_pairs_hook=_unique,parse_constant=_reject_constant)
    def fresh_preconditions():
        if _read(claim,'reservation.json',1048576)[0]!=reservation_raw:
            raise ValueError('Original reservation changed')
        try: os.stat('launch.json',dir_fd=claim,follow_symlinks=False)
        except FileNotFoundError: pass
        else: raise FileExistsError('Attempt already launched')
        # This observes preconditions only, not actual invocation or final VM stop.
        snapshot(work,reservation,stage='before')
    fresh_preconditions()
    raw=verify(nonce=nonce,reservation_sha256=hashlib.sha256(reservation_raw).hexdigest(),work=work,timeout=timeout)
    record=validate_receipt(raw,nonce=nonce,reservation_raw=reservation_raw,work=work,now=time.time())
    fresh_preconditions()
    if _read(state,'prepare-only',1)[0]!=b'': raise ValueError('Preparation hold changed')
    _exclusive_file(claim,MARKER,raw)
    os.fsync(claim)
    return dict(receipt=record,receipt_sha256=hashlib.sha256(raw).hexdigest())
