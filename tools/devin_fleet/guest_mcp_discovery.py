"""Generate the fixed discovery bootstrap from the existing trusted dispatcher."""
import guest_mcp_dispatch as baseline

COLLECT = '''    collector=sys.modules['mcp_probe_collect']
    binding=collector.collect(sys.argv[7].encode(),inspection_lease_id=sys.argv[8],state_directory=prepare.DISCOVERY_STATE)
    builder=module('trusted_discovery_inputs',DISCOVERY_INPUT_SOURCE)
    evidence=module('trusted_discovery_evidence',DISCOVERY_EVIDENCE_SOURCE)
    claim=collector._private_directory(collector.Path(prepare.DISCOVERY_STATE)/collector.CLAIM)
    try:
        names={'attempt.json','reservation.json',collector.MARKER,'launch.json','process-result.json'}
        if set(collector.os.listdir(claim))!=names: raise ValueError('Discovery claim changed')
        observed={name:collector._read(claim,name,1048576) for name in names}
        raw={name:value[0] for name,value in observed.items()}
        stop=collector.parsed(sys.argv[7].encode())
        if collector.sha(raw['reservation.json'])!=stop['reservation_sha256']:
            raise ValueError('Discovery reservation changed')
        if (collector.sha(raw['launch.json'])!=binding['launch_sha256'] or
                collector.sha(raw['process-result.json'])!=binding['process_result_sha256']):
            raise ValueError('Discovery launch binding changed')
        reservation=collector.parsed(raw['reservation.json'])
        admission=collector.validate_receipt(raw[collector.MARKER],nonce=stop['nonce'],reservation_raw=raw['reservation.json'])
        if admission['lease_id']!=stop['model_lease_id']:
            raise ValueError('Discovery stopped lease changed')
        if collector.parsed(raw['attempt.json'])!={'nonce':stop['nonce'],'work':admission['work'],'phase':'preparing'}:
            raise ValueError('Discovery locator changed')
        captured=collector.snapshot(admission['work'],reservation,stage='after')
        if (collector.sha(captured['export_raw'])!=binding['export_sha256'] or
                collector.sha(captured['audit_raw'])!=binding['audit_sha256']):
            raise ValueError('Discovery captured evidence changed')
        overrides=sys.modules['mcp_override_probe']
        inherited=overrides.read_global('mcp_config.json')
        expected=builder.make_input_builder(inherited)(admission['work'],stop['nonce'],tuple(reservation['audit_identity']))
        if expected!=captured['inputs']:
            raise ValueError('Exact discovery inputs required')
        candidate=evidence.summarize(collector.parsed(captured['export_raw']),captured['audit_raw'],stop['nonce'])
        if overrides.read_global('mcp_config.json')!=inherited:
            raise ValueError('Inherited discovery configuration changed')
        for name,original in observed.items():
            if collector._read(claim,name,1048576)!=original:
                raise ValueError('Discovery claim changed during classification')
        if set(collector.os.listdir(claim))!=names:
            raise ValueError('Discovery claim entries changed')
        result={'binding':binding,'discovery':candidate}
    finally: collector.os.close(claim)
'''


def make_probe(input_source,evidence_source):
    for source in (input_source,evidence_source):
        if type(source) is not str or not 0<len(source.encode())<=16384:
            raise ValueError('Bounded trusted discovery source required')
    code=baseline.PROBE
    def replace_once(old,new):
        nonlocal code
        if code.count(old)!=1:raise ValueError('Trusted dispatch bootstrap drift')
        code=code.replace(old,new,1)
    prepare="prepare=module('guest_mcp_prepare',sys.argv[1])"
    replace_once(prepare,
        "if not ((len(sys.argv)==7 and sys.argv[6]=='preflight') or "
        "(len(sys.argv)==8 and sys.argv[6]=='dispatch') or "
        "(len(sys.argv)==9 and sys.argv[6]=='collect')): raise ValueError('Fixed discovery action required')\n"
        +prepare+"\nprepare.STATE=prepare.DISCOVERY_STATE")
    replace_once('    inspect.inspect_prepared(sys.argv[3])',
                 '    inspect.inspect_discovery(sys.argv[3],'+repr(input_source)+')')
    collect="    result=sys.modules['mcp_probe_collect'].collect(sys.argv[7].encode(),inspection_lease_id=sys.argv[8])\n"
    addition=COLLECT.replace('DISCOVERY_INPUT_SOURCE',repr(input_source)).replace('DISCOVERY_EVIDENCE_SOURCE',repr(evidence_source))
    replace_once(collect,addition)
    if code.count("print('EBASE_MCP_DISPATCH:'")!=1:
        raise ValueError('Exact single dispatch output required')
    compile(code,'<trusted-discovery-bootstrap>','exec')
    return code
