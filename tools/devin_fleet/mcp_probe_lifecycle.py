"""Fixed trusted orchestration library; deliberately no public activation CLI.

Caller owns managed service and signal cleanup. No retry or fence removal.
Permission acceptance stays false pending review of an actual completed run.
"""
import hashlib
import json
from pathlib import Path
import re
import tempfile
import time

from durable import atomic_write_json
from guest_mcp_dispatch import PROBE,encode_support,validate_preflight
from guest_mcp_prepare import encode_sources
from managed_cli_guard import require_managed_namespace
from mcp_maintenance_network import machine_probe_network,IMAGE
from mcp_maintenance_restart import RUN,MACHINE
from model_network_admission import check_network
from observed_boundary_admission import make_boundary_check
from sandbox_capacity_probe import ROOT,inventory
from sandbox_runtime import SandboxRuntime
from validation_dispatch_receipt import _pairs
from validation_snapshot_input import _file
from turn_validation_result import same_json


def sha(raw): return hashlib.sha256(raw).hexdigest()


def _lease(repo):
    value=repo.log_dir.parent.name
    if re.fullmatch('[0-9a-f]{32}',value) is None: raise ValueError('Runtime operation identity required')
    return value


def _execute(repo,action,*,timeout,admission=None,stop_raw=None):
    if action not in ('preflight','dispatch','collect'): raise ValueError('Fixed action required')
    command=['/usr/bin/python3','-I','-c',PROBE,
             _file(ROOT/'guest_mcp_prepare.py',16384).decode(),
             _file(ROOT/'guest_mcp_inspect.py',16384).decode(),encode_sources(ROOT),encode_support(ROOT),
             _file(ROOT/'guest_mcp_dispatch.py',16384).decode(),action]
    if action=='dispatch': command.append(admission.decode('utf-8'))
    if action=='collect': command.extend([stop_raw.decode('utf-8'),_lease(repo)])
    log=repo.log_dir/('mcp-'+action+'.log')
    result=repo.controller.execute(command,cwd='/',log_path=log,timeout=timeout,
                                   max_log_bytes=16384,external_stop=repo.external_stop)
    if type(result.returncode) is not int or result.returncode!=0:
        raise RuntimeError('Fixed guest stage failed')
    prefix='EBASE_MCP_DISPATCH:'
    lines=[line[len(prefix):] for line in _file(log,16384).decode().splitlines() if line.startswith(prefix)]
    if len(lines)!=1: raise ValueError('Missing exact guest stage receipt')
    return json.loads(lines[0],object_pairs_hook=_pairs)


def _process(value,nonce):
    expected=dict(returncode=0,timed_out=False,leader_reaped=True,process_group_stop_requested=True,
                  all_descendants_stopped=False,raw_output_suppressed=True,nonce=nonce,
                  phase='awaiting_vm_stop',passed=False,production_admitted=False,resume_used=False)
    if (type(value) is not dict or set(value)!=set(expected)
            or any(type(value[k]) is not type(v) or value[k]!=v for k,v in expected.items())):
        raise ValueError('Successful bounded dispatch required')
    return value


def _collection(value,*,preflight,admission_raw,stop_raw,inspection):
    flags={'expected_call_observed','discovery_verified','exact_model_verified','linked_denial_observed',
           'execution_marker_seen','production_admitted','permission_denial_observed','passed',
           'evidence_bound','live_execution_verified','inspection_vm_stopped'}
    hashes={'audit_sha256','export_sha256','supervision_sha256','session_sha256',
            'stop_receipt_sha256','launch_sha256','process_result_sha256'}
    if (type(value) is not dict or set(value)!=flags|hashes|{'tool_call_count','attempt_nonce','inspection_lease_id'}
            or any(type(value[k]) is not bool for k in flags)
            or any(type(value[k]) is not str or re.fullmatch('[0-9a-f]{64}',value[k]) is None for k in hashes)
            or type(value['tool_call_count']) is not int or not 0<=value['tool_call_count']<=256
            or value['attempt_nonce']!=preflight['nonce'] or value['inspection_lease_id']!=inspection
            or value['supervision_sha256']!=sha(admission_raw) or value['stop_receipt_sha256']!=sha(stop_raw)
            or any(value[k] for k in ('passed','production_admitted','live_execution_verified','inspection_vm_stopped'))
            or value['evidence_bound'] is not True):
        raise ValueError('Bound non-accepting collection required')
    return value


def run_probe(registration):
    return _run_probe(registration,execute=_execute,network=machine_probe_network,
                      collection=_collection,evidence_prefix='mcp-lifecycle-')


def _run_probe(registration,*,execute,network,collection,evidence_prefix):
    # Trusted fixed controller adapters only; never supplied by model or CLI args.
    if evidence_prefix not in ('mcp-lifecycle-','mcp-discovery-lifecycle-','mcp-wildcard-lifecycle-','mcp-echo-control-lifecycle-','mcp-compatible-control-lifecycle-','mcp-params-control-lifecycle-'):
        raise ValueError('Fixed evidence namespace required')
    require_managed_namespace()
    if (registration.get('production_enabled') is not False
            or registration['roles']['machine'].get('id')!=MACHINE):
        raise ValueError('Fixed nonproduction registration required')
    evidence=Path(tempfile.mkdtemp(prefix=evidence_prefix,dir=ROOT))
    record=dict(schema=1,phase='preflight',passed=False,production_admitted=False,
                permission_denial_accepted=False,all_vms_stopped=False)
    atomic_write_json(evidence/'receipt.json',record)
    boundary=make_boundary_check(IMAGE)
    try:
        with SandboxRuntime(registration,ROOT,capacity=1) as runtime:
            current=json.loads(_file(ROOT/'sandbox-registry.json',1048576),object_pairs_hook=_pairs)
            if not same_json(current,runtime.registration): raise ValueError('Locked registration changed')
            inventory(runtime.registration)
            check_network(runtime,'machine',stage='initial',repo=None,timeout=45)
            boundary(runtime,'machine',stage='initial',repo=None,timeout=60)
            with runtime.role('machine') as repo:
                model_lease=_lease(repo)
                boundary(runtime,'machine',stage='before_prepare',repo=repo,timeout=60)
                preflight=validate_preflight(execute(repo,'preflight',timeout=30))
                record['preflight']=preflight
                with network(runtime,repo,timeout=240) as budget:
                    started=time.monotonic()
                    now=int(time.time())
                    duration=min(180,int(budget)-10)
                    if duration<20: raise TimeoutError('Insufficient dispatch budget')
                    admission=dict(schema=2,nonce=preflight['nonce'],work=preflight['work'],
                                   reservation_sha256=preflight['reservation_sha256'],machine_vm_id=MACHINE,
                                   lease_id=model_lease,issued_at=now,expires_at=now+duration,
                                   session_inventory_scope='current_workdir',session_inventory_verified=True,
                                   fresh_attempt_preconditions_verified=True,previous_sessions=[])
                    atomic_write_json(evidence/'admission.json',admission)
                    admission_raw=_file(evidence/'admission.json',65536)
                    record['phase']='dispatching'; atomic_write_json(evidence/'receipt.json',record)
                    result=execute(repo,'dispatch',timeout=min(duration+5,budget-(time.monotonic()-started)),admission=admission_raw)
                    record['process']=_process(result,preflight['nonce'])
            # Leaving both contexts must restore network and stop the model lease.
            inventory(runtime.registration)
            check_network(runtime,'machine',stage='initial',repo=None,timeout=45)
            stop=dict(schema=1,machine_vm_id=MACHINE,model_lease_id=model_lease,nonce=preflight['nonce'],
                      reservation_sha256=preflight['reservation_sha256'],model_vm_stopped=True,network_denied=True)
            atomic_write_json(evidence/'model-stop.json',stop)
            stop_raw=_file(evidence/'model-stop.json',65536)
            record['phase']='collecting'; atomic_write_json(evidence/'receipt.json',record)
            with runtime.role('machine') as repo:
                inspection=_lease(repo)
                if inspection==model_lease: raise ValueError('Inspection lease must be distinct')
                boundary(runtime,'machine',stage='before_inspection',repo=repo,timeout=60)
                observed=execute(repo,'collect',timeout=30,stop_raw=stop_raw)
                record['collection']=collection(observed,preflight=preflight,admission_raw=admission_raw,
                                                  stop_raw=stop_raw,inspection=inspection)
            inventory(runtime.registration)
            check_network(runtime,'machine',stage='initial',repo=None,timeout=45)
            record.update(phase='complete',all_vms_stopped=True,inspection_vm_stopped=True)
    finally:
        atomic_write_json(evidence/'receipt.json',record)
    return dict(evidence=str(evidence),**record)
