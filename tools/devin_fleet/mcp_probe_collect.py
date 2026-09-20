"""Read-only guest evidence binding after an outer-observed model-lease stop.

The inspection VM is running while this code executes. Neither guest files nor
the supplied stop receipt prove external lifecycle observations. The outer owner
must match receipt hashes to its own records and stop the inspection lease too.
"""
import hashlib
import json
import os
from pathlib import Path
import re

from guest_mcp_prepare import STATE
from machine_cli_smoke import CLI
from model_catalog_policy import MODEL,_unique,_reject_constant
from mcp_probe_reservation import CLAIM,_private_directory
from mcp_probe_snapshot import _read,snapshot
from mcp_probe_supervision import MACHINE,MARKER,validate_receipt,bind_supervised_probe


def sha(raw): return hashlib.sha256(raw).hexdigest()


def parsed(raw): return json.loads(raw,object_pairs_hook=_unique,parse_constant=_reject_constant)


def collect(stop_raw,*,inspection_lease_id,state_directory=STATE):
    if type(stop_raw) is not bytes or not 0<len(stop_raw)<=4096:
        raise ValueError('Bounded outer stop receipt required')
    stop=parsed(stop_raw)
    if (type(stop) is not dict or set(stop)!={'schema','machine_vm_id','model_lease_id','nonce',
            'reservation_sha256','model_vm_stopped','network_denied'}
            or type(stop['schema']) is not int or stop['schema']!=1
            or stop['machine_vm_id']!=MACHINE or stop['model_vm_stopped'] is not True
            or stop['network_denied'] is not True
            or any(type(stop[key]) is not str or re.fullmatch('[0-9a-f]{32}',stop[key]) is None for key in ('model_lease_id','nonce'))
            or type(inspection_lease_id) is not str or re.fullmatch('[0-9a-f]{32}',inspection_lease_id) is None
            or inspection_lease_id==stop['model_lease_id']):
        raise ValueError('Distinct inspection lease and bound model-stop receipt required')
    state=_private_directory(state_directory)
    claim=None
    try:
        if _read(state,'prepare-only',1)[0]!=b'': raise ValueError('Hold changed')
        claim=_private_directory(Path(state_directory)/CLAIM)
        names={'attempt.json','reservation.json',MARKER,'launch.json','process-result.json'}
        if set(os.listdir(claim))!=names: raise ValueError('Complete exact attempted claim required')
        raw={name:_read(claim,name,1048576)[0] for name in names}
        reservation=parsed(raw['reservation.json'])
        if sha(raw['reservation.json'])!=stop['reservation_sha256']:
            raise ValueError('Outer reservation binding differs')
        admission=validate_receipt(raw[MARKER],nonce=stop['nonce'],reservation_raw=raw['reservation.json'])
        if admission['lease_id']!=stop['model_lease_id']: raise ValueError('Stopped model lease differs')
        locator=parsed(raw['attempt.json'])
        if locator!={'nonce':stop['nonce'],'work':admission['work'],'phase':'preparing'}:
            raise ValueError('Attempt locator differs')
        launch=parsed(raw['launch.json'])
        launch_keys={'nonce','phase','model','main_config_sha256','catalog_sha256','resume_used','work',
                     'input_sha256','reservation_sha256','argv_sha256','supervision'}
        if (type(launch) is not dict or set(launch)!=launch_keys or launch['nonce']!=stop['nonce']
                or launch['phase']!='attempted' or launch['model']!=MODEL or launch['resume_used'] is not False
                or launch['work']!=admission['work'] or launch['input_sha256']!=reservation.get('input_sha256')
                or launch['reservation_sha256']!=stop['reservation_sha256']
                or launch['supervision']!={'receipt':admission,'receipt_sha256':sha(raw[MARKER])}
                or any(type(launch[k]) is not str or re.fullmatch('[0-9a-f]{64}',launch[k]) is None
                       for k in ('main_config_sha256','catalog_sha256','argv_sha256'))):
            raise ValueError('Exact supervised launch record required')
        process=parsed(raw['process-result.json'])
        expected=dict(returncode=0,timed_out=False,leader_reaped=True,process_group_stop_requested=True,
                      all_descendants_stopped=False,raw_output_suppressed=True,nonce=stop['nonce'],
                      phase='awaiting_vm_stop',passed=False,production_admitted=False,resume_used=False)
        if (type(process) is not dict or set(process)!=set(expected)
                or any(type(process[k]) is not type(v) or process[k]!=v for k,v in expected.items())):
            raise ValueError('Successful bounded process result required')
        captured=snapshot(admission['work'],reservation,stage='after')
        work=admission['work']
        argv=[CLI,'--config',work+'/config.json','--model',MODEL,'--permission-mode','normal',
              '--respect-workspace-trust','false','--export',work+'/export.json','--print',
              captured['inputs']['prompt.txt'].decode('utf-8')]
        if sha(json.dumps(argv).encode())!=launch['argv_sha256']:
            raise ValueError('Fixed non-resume invocation differs')
        completion=dict(nonce=stop['nonce'],returncode=0,processes_stopped=True,
                        audit_identity=captured['audit_identity'],resume_used=False,
                        audit_sha256=sha(captured['audit_raw']),export_sha256=sha(captured['export_raw']))
        # Inputs match the original reserved hashes; this does not pretend that a
        # second before-stage capture occurred during offline inspection.
        result=bind_supervised_probe(raw['reservation.json'],raw[MARKER],completion,
                                    inputs_before=captured['inputs'],inputs_after=captured['inputs'],
                                    audit_raw=captured['audit_raw'],export_raw=captured['export_raw'])
        for name,original in raw.items():
            if _read(claim,name,1048576)[0]!=original: raise ValueError('Claim changed during collection')
        session=result.pop('session_id')
        result.update(session_sha256=sha(session.encode()),stop_receipt_sha256=sha(stop_raw),
                      launch_sha256=sha(raw['launch.json']),process_result_sha256=sha(raw['process-result.json']),
                      inspection_lease_id=inspection_lease_id,inspection_vm_stopped=False)
        return result
    finally:
        if claim is not None: os.close(claim)
        os.close(state)
