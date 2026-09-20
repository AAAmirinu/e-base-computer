"""Fixed discovery-only adapters for the shared bounded maintenance lifecycle."""
import json
from guest_mcp_dispatch import encode_support
from guest_mcp_discovery import make_probe
from guest_mcp_prepare import encode_sources
from mcp_maintenance_network import discovery_probe_network
from mcp_probe_lifecycle import ROOT,_lease,_collection,_run_probe
from validation_dispatch_receipt import _pairs
from validation_snapshot_input import _file


def execute(repo,action,*,timeout,admission=None,stop_raw=None):
    if action not in ('preflight','dispatch','collect'):raise ValueError('Fixed discovery action required')
    bootstrap=make_probe(_file(ROOT/'mcp_discovery_inputs.py',16384).decode(),
                         _file(ROOT/'mcp_discovery_evidence.py',16384).decode())
    command=['/usr/bin/python3','-I','-c',bootstrap,
             _file(ROOT/'guest_mcp_prepare.py',16384).decode(),
             _file(ROOT/'guest_mcp_inspect.py',16384).decode(),encode_sources(ROOT),encode_support(ROOT),
             _file(ROOT/'guest_mcp_dispatch.py',16384).decode(),action]
    if action=='dispatch':command.append(admission.decode())
    if action=='collect':command.extend([stop_raw.decode(),_lease(repo)])
    log=repo.log_dir/('discovery-'+action+'.log')
    result=repo.controller.execute(command,cwd='/',log_path=log,timeout=timeout,
                                   max_log_bytes=16384,external_stop=repo.external_stop)
    if type(result.returncode) is not int or result.returncode!=0:raise RuntimeError('Discovery guest stage failed')
    prefix='EBASE_MCP_DISPATCH:'
    lines=[line[len(prefix):] for line in _file(log,16384).decode().splitlines() if line.startswith(prefix)]
    if len(lines)!=1:raise ValueError('Exact discovery receipt required')
    return json.loads(lines[0],object_pairs_hook=_pairs)


def collection(value,**binding):
    if type(value) is not dict or set(value)!={'binding','discovery'}:raise ValueError('Bound discovery collection required')
    verified=_collection(value['binding'],**binding)
    candidate=value['discovery']
    counters={'tool_call_count':4096,'observation_count':4096,'linked_result_count':4096,
              'audit_initialization_count':64,'audit_list_count':64,'audit_call_count':64}
    flags={'call_ids_unique','expected_list_call_observed','listed_schema_verified','exact_model_verified',
           'audit_nonce_verified','discovery_sequence_observed','consistent','passed','production_admitted'}
    if (type(candidate) is not dict or set(candidate)!=set(counters)|flags
            or any(type(candidate[k]) is not int or not 0<=candidate[k]<=v for k,v in counters.items())
            or any(type(candidate[k]) is not bool for k in flags)
            or candidate['passed'] is not False or candidate['production_admitted'] is not False
            or candidate['tool_call_count']!=verified['tool_call_count']
            or candidate['exact_model_verified']!=verified['exact_model_verified']):
        raise ValueError('Finite non-accepting discovery candidate required')
    expected=(candidate['tool_call_count']==candidate['observation_count']==candidate['linked_result_count']==1
              and all(candidate[k] for k in ('call_ids_unique','expected_list_call_observed','listed_schema_verified',
                       'exact_model_verified','audit_nonce_verified','discovery_sequence_observed'))
              and candidate['audit_initialization_count']>=1 and candidate['audit_list_count']>=1
              and candidate['audit_call_count']==0)
    if candidate['consistent']!=expected:raise ValueError('Inconsistent discovery candidate')
    return dict(binding=verified,discovery=candidate)


def run_discovery(registration):
    return _run_probe(registration,execute=execute,network=discovery_probe_network,
                      collection=collection,evidence_prefix='mcp-discovery-lifecycle-')
