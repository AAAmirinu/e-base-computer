"""Fixed closed-network reinspection of the completed v2 attempt; no CLI call."""
import json
from pathlib import Path
import tempfile

from durable import atomic_write_json
from guest_mcp_dispatch import PROBE,encode_support
from guest_mcp_prepare import encode_sources
from managed_cli_guard import require_managed_namespace
from mcp_maintenance_network import IMAGE
from mcp_maintenance_restart import MACHINE
from mcp_probe_entry import interruption_cleanup
from mcp_probe_lifecycle import _lease
from mcp_result_summary import validate
from model_network_admission import check_network
from observed_boundary_admission import make_boundary_check
from sandbox_capacity_probe import ROOT,inventory
from sandbox_runtime import SandboxRuntime
from validation_dispatch_receipt import _pairs
from validation_snapshot_input import _file

EVIDENCE=ROOT/'mcp-lifecycle-_5t63hfq'
EXPORT_SHA='59c89be8e4fe662930017a3d20b3e72e92539b89875ce6c54b2ef80f5552a47f'
AUDIT_SHA='dbac9579ed901ce8a8841493556b6715abae6cb9f21d3bbd07e1f271a502e148'


def probe(source):
    # The original bootstrap executes collect only, loading controller-supplied
    # modules. It does not import code from the saved model workspace.
    return PROBE+'\n'+'''summary=module('mcp_result_summary',SUMMARY_SOURCE)
collector=sys.modules['mcp_probe_collect']
claim=collector._private_directory(collector.Path(collector.STATE)/collector.CLAIM)
try:
    reservation=collector.parsed(collector._read(claim,'reservation.json',1048576)[0])
    admission=collector.parsed(collector._read(claim,collector.MARKER,1048576)[0])
finally: collector.os.close(claim)
captured=collector.snapshot(admission['work'],reservation,stage='after')
if collector.sha(captured['export_raw'])!=result['export_sha256'] or collector.sha(captured['audit_raw'])!=result['audit_sha256']:
    raise ValueError('Collected evidence changed')
finite=summary.summarize(collector.parsed(captured['export_raw']),captured['audit_raw'],admission['nonce'])
print('EBASE_MCP_RESULT_SUMMARY:'+json.dumps(summary.validate(finite)))
'''.replace('SUMMARY_SOURCE',repr(source))


def discovery_probe(source, classifier_raw):
    from guest_mcp_discovery import make_probe
    code=make_probe(_file(ROOT/'mcp_discovery_inputs.py',16384).decode(),
                    classifier_raw.decode())
    return code+'\n'+"shape=module('trusted_discovery_shape',"+repr(source)+")\n"+\
        "print('EBASE_MCP_RESULT_SUMMARY:'+json.dumps(shape.validate(shape.summarize(collector.parsed(captured['export_raw'])))))\n"


def wildcard_probe(source,classifier_raw):
    from guest_mcp_wildcard import make_probe
    code=make_probe(_file(ROOT/'mcp_wildcard_denial_inputs.py',16384).decode(),
        classifier_raw.decode(),_file(ROOT/'mcp_discovery_evidence.py',16384).decode(),source)
    return code+'\n'+"summary=sys.modules['mcp_result_summary']\n"+\
        "finite=summary.summarize(collector.parsed(captured['export_raw']),captured['audit_raw'],stop['nonce'])\n"+\
        "print('EBASE_MCP_RESULT_SUMMARY:'+json.dumps(summary.validate(finite)))\n"+\
        "template=module('trusted_refusal_template',"+repr(_file(ROOT/'mcp_refusal_template.py',16384).decode())+")\n"+\
        "print('EBASE_MCP_REFUSAL_TEMPLATE:'+json.dumps(template.summarize(collector.parsed(captured['export_raw']),captured['audit_raw'],stop['nonce'])))\n"


def control_probe(source,classifier_raw,*,compatible=False):
    if type(compatible) is not bool:raise ValueError('Fixed control profile required')
    from guest_mcp_wildcard import make_control_probe
    builder=_file(ROOT/'mcp_echo_control_inputs.py',16384).decode()
    if compatible:
        from guest_mcp_wildcard import make_compatible_control_probe as make_control_probe
        from mcp_compatible_control_source import compose
        builder=compose(builder,_file(ROOT/'mcp_fixture_compat.py',16384).decode())
    code=make_control_probe(builder,
        classifier_raw.decode(),_file(ROOT/'mcp_discovery_evidence.py',16384).decode(),source,
        _file(ROOT/'mcp_wildcard_denial_evidence.py',16384).decode())
    return code+'\n'+"summary=sys.modules['mcp_result_summary']\n"+\
        "finite=summary.summarize(collector.parsed(captured['export_raw']),captured['audit_raw'],stop['nonce'])\n"+\
        "print('EBASE_MCP_RESULT_SUMMARY:'+json.dumps(summary.validate(finite)))\n"+\
        "template=module('trusted_refusal_template',"+repr(_file(ROOT/'mcp_refusal_template.py',16384).decode())+")\n"+\
        "print('EBASE_MCP_REFUSAL_TEMPLATE:'+json.dumps(template.summarize(collector.parsed(captured['export_raw']),captured['audit_raw'],stop['nonce'])))\n"


def main(*,discovery=False,wildcard=False,control=False,compatible=False):
    if type(control) is not bool or type(compatible) is not bool or (compatible and control):raise ValueError('Fixed inspection kind required')
    control=control or compatible
    if type(control) is not bool or (control and (discovery or wildcard)):raise ValueError('Fixed inspection kind required')
    if type(wildcard) is not bool or (wildcard and discovery):raise ValueError('Fixed inspection kind required')
    if type(discovery) is not bool:raise ValueError('Fixed inspection kind required')
    evidence=EVIDENCE
    export_sha,audit_sha=EXPORT_SHA,AUDIT_SHA
    create_probe,summary_file,check_summary=probe,'mcp_result_summary.py',validate
    if discovery:
        from mcp_discovery_shape import validate as check_summary
        evidence=ROOT/'mcp-discovery-lifecycle-pmpssixf'
        export_sha='d342589ac1266a47dd6ff8c300cd6b4b78eca011a00985ab36e11b19f5558419'
        audit_sha='35313004315a6176a92d7206848d40129bcff9d3d7816b203d630ca80b5bf461'
        create_probe,summary_file=discovery_probe,'mcp_discovery_shape.py'
    if wildcard:
        evidence=ROOT/'mcp-wildcard-lifecycle-h2dcw84e'
        export_sha='d57980b5610511ad437cbcb03f51a22e617c1766be5626ada41fd976e0cdbb09'
        audit_sha='23ef0bcf89b745395bdb3116232405ac8313981bf82982ed3af5c48165b450f1'
    if control:
        evidence=ROOT/'mcp-echo-control-lifecycle-r2urx45p'
        export_sha='f85a9dcfbb1b2b2815143e44ea154b317c287d37567591af58a93d750254e180'
        audit_sha='e8e2f8c71883ef0a7ea8f1c961e1040090c152ddca73f688a614f33acb0582f1'
    if compatible:
        evidence=ROOT/'mcp-compatible-control-lifecycle-g6_x4mr7'
        export_sha='cedd34e3c628db5d6982d97991e8d2103d0e37d8303852c99c6f406283d5c02f'
        audit_sha='3a0b8052a48b4810cd03b2a6ee22446a75ef3de298022e4eeeafa59275da6fba'
    require_managed_namespace()
    registration=json.loads(_file(ROOT/'sandbox-registry.json',1048576),object_pairs_hook=_pairs)
    if registration.get('production_enabled') is not False or registration['roles']['machine'].get('id')!=MACHINE:
        raise ValueError('Fixed nonproduction machine required')
    original=json.loads(_file(evidence/'receipt.json',65536),object_pairs_hook=_pairs)
    previous=original.get('collection',{})
    if discovery or wildcard or control:previous=previous.get('binding',{})
    if (original.get('phase')!='complete' or original.get('all_vms_stopped') is not True
            or original.get('inspection_vm_stopped') is not True
            or previous.get('export_sha256')!=export_sha
            or previous.get('audit_sha256')!=audit_sha):
        raise ValueError('Completed fixed v2 evidence required')
    stop_raw=_file(evidence/'model-stop.json',4096)
    work=Path(tempfile.mkdtemp(prefix='compatible-result-inspection-' if compatible else 'control-result-inspection-' if control else 'wildcard-result-inspection-' if wildcard else 'discovery-result-inspection-' if discovery else 'mcp-result-inspection-',dir=ROOT))
    record=dict(phase='checking',network_changed=False,cli_executed=False,model_executed=False,
                raw_evidence_exported=False,permission_denial_accepted=False,production_admitted=False)
    try:
        with interruption_cleanup(),SandboxRuntime(registration,ROOT,capacity=1) as runtime:
            inventory(registration)
            check_network(runtime,'machine',stage='initial',repo=None,timeout=45)
            boundary=make_boundary_check(IMAGE)
            boundary(runtime,'machine',stage='initial',repo=None,timeout=60)
            with runtime.role('machine') as repo:
                boundary(runtime,'machine',stage='before_inspection',repo=repo,timeout=60)
                check_network(runtime,'machine',stage='before_inspection',repo=repo,timeout=45)
                summary_source=_file(ROOT/summary_file,16384).decode()
                if control:
                    classifier_raw=_file(ROOT/'mcp_echo_control_evidence.py',16384)
                    bootstrap=control_probe(summary_source,classifier_raw,compatible=compatible)
                    bootstrap+='\nfailure=module("trusted_control_failure",'+repr(_file(ROOT/'mcp_control_failure_shape.py',16384).decode())+')\n'
                    bootstrap+="print('EBASE_MCP_CONTROL_FAILURE:'+json.dumps(failure.summarize(collector.parsed(captured['export_raw']),captured['audit_raw'],stop['nonce'])))\n"
                elif wildcard:
                    classifier_raw=_file(ROOT/'mcp_wildcard_denial_evidence.py',16384)
                    bootstrap=wildcard_probe(summary_source,classifier_raw)
                elif discovery:
                    classifier_raw=_file(ROOT/'mcp_discovery_evidence.py',16384)
                    bootstrap=discovery_probe(summary_source,classifier_raw)
                else:
                    bootstrap=create_probe(summary_source)
                command=['/usr/bin/python3','-I','-c',bootstrap,
                         _file(ROOT/'guest_mcp_prepare.py',16384).decode(),
                         _file(ROOT/'guest_mcp_inspect.py',16384).decode(),encode_sources(ROOT),encode_support(ROOT),
                         _file(ROOT/'guest_mcp_dispatch.py',16384).decode(),'collect',stop_raw.decode(),_lease(repo)]
                log=work/'summary.log'
                result=repo.controller.execute(command,cwd='/',log_path=log,timeout=30,
                                               max_log_bytes=16384,external_stop=repo.external_stop)
                if result.returncode!=0: raise RuntimeError('Closed evidence inspection failed')
                lines=_file(log,16384).decode().splitlines()
                def extract(prefix):
                    rows=[line[len(prefix):] for line in lines if line.startswith(prefix)]
                    if len(rows)!=1: raise ValueError('Exact finite result required')
                    return json.loads(rows[0],object_pairs_hook=_pairs)
                bound=extract('EBASE_MCP_DISPATCH:')
                if discovery or wildcard or control:
                    if control:
                        from mcp_echo_control_collection import collection
                    elif wildcard:
                        from mcp_wildcard_denial_collection import collection
                    else:
                        from mcp_discovery_lifecycle import collection
                    import hashlib
                    verified=collection(bound,preflight=original['preflight'],
                        admission_raw=_file(evidence/'admission.json',65536),stop_raw=stop_raw,inspection=_lease(repo))
                    kind='control' if control else 'wildcard' if wildcard else 'discovery'
                    record[kind+'_reclassification']=verified[kind]
                    record['classifier_sha256']=hashlib.sha256(classifier_raw).hexdigest()
                    bound=verified['binding']
                if (bound.get('evidence_bound') is not True or bound.get('export_sha256')!=export_sha
                        or bound.get('audit_sha256')!=audit_sha
                        or bound.get('stop_receipt_sha256')!=previous['stop_receipt_sha256']
                        or bound.get('inspection_lease_id')!=_lease(repo)):
                    raise ValueError('Original immutable evidence binding required')
                record['summary']=check_summary(extract('EBASE_MCP_RESULT_SUMMARY:'))
                if control:
                    from mcp_control_failure_shape import validate as validate_failure
                    record['failure_indicators']=validate_failure(extract('EBASE_MCP_CONTROL_FAILURE:'))
                if wildcard or control:
                    from mcp_refusal_template import validate as validate_template
                    record['refusal_template']=validate_template(extract('EBASE_MCP_REFUSAL_TEMPLATE:'))
            inventory(registration)
            check_network(runtime,'machine',stage='initial',repo=None,timeout=45)
            record.update(phase='closed',all_vms_stopped=True,network_denied=True)
    finally: atomic_write_json(work/'receipt.json',record)
    print(json.dumps(dict(evidence=str(work),**record)),flush=True)


if __name__=='__main__':
    import sys
    if sys.argv[1:] not in ([],['--discovery'],['--wildcard'],['--control'],['--compatible']):raise ValueError('Fixed inspection action required')
    main(discovery=sys.argv[1:]==['--discovery'],wildcard=sys.argv[1:]==['--wildcard'],control=sys.argv[1:]==['--control'],compatible=sys.argv[1:]==['--compatible'])
