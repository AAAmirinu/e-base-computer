"""Fail closed before any runtime resumes a VM after the fixed MCP experiment.

This is read-only. No recovery, marker deletion or automatic retry is permitted.
The future maintenance window must write this fixed reservation before mutation.
"""
import json
import os
from pathlib import Path
from model_network_admission import check_network
from sandbox_turn_fence import _directory
from validation_snapshot_input import _file
from validation_dispatch_receipt import _pairs

PREVIOUS_RUN=Path('/home/fleet/controller-validation/mcp-live-v1')
RUN=Path('/home/fleet/controller-validation/mcp-live-v2')
DISCOVERY_RUN=Path('/home/fleet/controller-validation/mcp-discovery-live-v1')
WILDCARD_RUN=Path('/home/fleet/controller-validation/mcp-wildcard-live-v1')
PREVIOUS_CONTROL_RUN=Path('/home/fleet/controller-validation/mcp-echo-control-live-v1')
CONTROL_RUN=Path('/home/fleet/controller-validation/mcp-echo-control-live-v2')
COMPATIBLE_CONTROL_RUN=Path('/home/fleet/controller-validation/mcp-echo-compatible-live-v1')
PARAMS_CONTROL_RUN=Path('/home/fleet/controller-validation/mcp-echo-params-live-v1')
PREVIOUS_CATALOG_RUN=Path('/home/fleet/controller-validation/catalog-diagnostic-v1')
# One additional catalog-only attempt explicitly approved by the user.
SECOND_CATALOG_RUN=Path('/home/fleet/controller-validation/catalog-diagnostic-v2')
THIRD_CATALOG_RUN=Path('/home/fleet/controller-validation/catalog-diagnostic-v3')
FOURTH_CATALOG_RUN=Path('/home/fleet/controller-validation/catalog-diagnostic-v4')
CATALOG_RUN=Path('/home/fleet/controller-validation/catalog-diagnostic-v5')
MACHINE='40e32a36-d565-4853-a841-fa3bea9ac648'


def require_closed_maintenance(runtime):
    for path in (PREVIOUS_RUN,RUN,PREVIOUS_CATALOG_RUN,SECOND_CATALOG_RUN,THIRD_CATALOG_RUN,FOURTH_CATALOG_RUN,CATALOG_RUN,DISCOVERY_RUN,WILDCARD_RUN,PREVIOUS_CONTROL_RUN,CONTROL_RUN,COMPATIBLE_CONTROL_RUN,PARAMS_CONTROL_RUN):
        require_closed_path(runtime,path)


def require_closed_path(runtime,run):
    if not os.path.lexists(run): return
    # Presence of even a partially prepared run means inspection is required.
    for parent in run.parents: _directory(parent,private=False)
    _directory(run,private=True)
    raw=_file(run/'network-attempt.json',65536)
    reservation=json.loads(raw,object_pairs_hook=_pairs)
    expected=dict(schema=1,sandbox_id=MACHINE,run_directory=str(run),state='reserved',automatic_resume=False)
    if reservation!=expected or type(reservation.get('schema')) is not int or reservation.get('automatic_resume') is not False:
        raise ValueError('Unknown fixed MCP maintenance reservation')
    entry=runtime.registration['roles']['machine']
    if entry.get('id')!=MACHINE or entry.get('name')!='e-base-machine':
        raise ValueError('Fixed maintenance VM identity changed')
    window=run/'network-window'
    _directory(window,private=True)
    window_raw=_file(window/'network-window.json',65536)
    record=json.loads(window_raw,object_pairs_hook=_pairs)
    required={'schema','role','sandbox_id','phase','network_denied_after','automatic_resume','created_deny_ids'}
    if (type(record) is not dict or not required<=set(record) or set(record)-required-{'original_deny_id'}
            or type(record['schema']) is not int or record['schema']!=1 or record['role']!='machine'
            or record['sandbox_id']!=MACHINE or record['phase']!='closed'
            or record['network_denied_after'] is not True or record['automatic_resume'] is not False
            or type(record['created_deny_ids']) is not list
            or any(type(s) is not str for s in record['created_deny_ids'])):
        raise ValueError('MCP maintenance network recovery required')
    check_network(runtime,'machine',stage='initial',repo=None,timeout=45)
    if _file(run/'network-attempt.json',65536)!=raw or _file(window/'network-window.json',65536)!=window_raw:
        raise ValueError('MCP maintenance reservation changed')
