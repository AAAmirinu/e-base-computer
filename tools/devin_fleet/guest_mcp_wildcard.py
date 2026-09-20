"""Fixed wildcard probe bootstrap; caller owns admission/network/VM lifecycle."""
import guest_mcp_dispatch as baseline
from guest_mcp_discovery import COLLECT


def make_probe(input_source, evidence_source, discovery_source, result_source):
    return _make_probe(input_source,evidence_source,discovery_source,result_source)


def make_control_probe(input_source,evidence_source,discovery_source,result_source,sequence_source):
    if type(sequence_source) is not str or not 0<len(sequence_source.encode())<=16384:
        raise ValueError('Bounded trusted control sequence required')
    return _make_probe(input_source,evidence_source,discovery_source,result_source,sequence_source=sequence_source)


def make_compatible_control_probe(input_source,evidence_source,discovery_source,result_source,sequence_source):
    if type(sequence_source) is not str or not 0<len(sequence_source.encode())<=16384:
        raise ValueError('Bounded trusted control sequence required')
    return _make_probe(input_source,evidence_source,discovery_source,result_source,
                       sequence_source=sequence_source,compatible=True)


def make_params_control_probe(input_source,evidence_source,discovery_source,result_source,sequence_source):
    if type(sequence_source) is not str or not 0<len(sequence_source.encode())<=16384:
        raise ValueError('Bounded trusted control sequence required')
    return _make_probe(input_source,evidence_source,discovery_source,result_source,
                       sequence_source=sequence_source,params=True)


def _make_probe(input_source,evidence_source,discovery_source,result_source,*,sequence_source=None,compatible=False,params=False):
    if (type(compatible) is not bool or type(params) is not bool or (compatible and params)
            or ((compatible or params) and sequence_source is None)):
        raise ValueError('Explicit compatible control profile required')
    for source in (input_source, evidence_source, discovery_source, result_source):
        if type(source) is not str or not 0 < len(source.encode()) <= 16384:
            raise ValueError('Bounded trusted wildcard source required')
    control=sequence_source is not None
    state='PARAMS_CONTROL_STATE' if params else 'COMPATIBLE_CONTROL_STATE' if compatible else 'CONTROL_STATE' if control else 'WILDCARD_STATE'
    inspector='inspect_params_control' if params else 'inspect_compatible_control' if compatible else 'inspect_control' if control else 'inspect_wildcard'
    result_key='control' if control else 'wildcard'
    code = baseline.PROBE
    def replace_once(old, new):
        nonlocal code
        if code.count(old) != 1:
            raise ValueError('Trusted wildcard bootstrap drift')
        code = code.replace(old, new, 1)
    prepare = "prepare=module('guest_mcp_prepare',sys.argv[1])"
    replace_once(prepare,
        "if not ((len(sys.argv)==7 and sys.argv[6]=='preflight') or "
        "(len(sys.argv)==8 and sys.argv[6]=='dispatch') or "
        "(len(sys.argv)==9 and sys.argv[6]=='collect')): raise ValueError('Fixed wildcard action required')\n"
        + prepare + '\nprepare.STATE=prepare.'+state)
    replace_once('    inspect.inspect_prepared(sys.argv[3])',
                 '    inspect.'+inspector+'(sys.argv[3],'+repr(input_source)+')')
    # Adapt the trusted template BEFORE embedding source strings; never replace
    # user text or already-embedded Python literals.
    if (COLLECT.count('prepare.DISCOVERY_STATE') != 2
            or COLLECT.count("result={'binding':binding,'discovery':candidate}") != 1):
        raise ValueError('Trusted wildcard collector drift')
    template = COLLECT.replace('prepare.DISCOVERY_STATE', 'prepare.'+state)
    template = template.replace("result={'binding':binding,'discovery':candidate}",
                                "result={'binding':binding,'"+result_key+"':candidate}")
    dependency = "    evidence=module('trusted_discovery_evidence',DISCOVERY_EVIDENCE_SOURCE)"
    if template.count(dependency) != 1:
        raise ValueError('Trusted wildcard collector drift')
    template = template.replace(dependency,
        "    module('mcp_discovery_evidence',WILDCARD_DISCOVERY_SOURCE)\n"
        "    module('mcp_result_summary',WILDCARD_RESULT_SOURCE)\n" +
        ("    module('mcp_wildcard_denial_evidence',CONTROL_SEQUENCE_SOURCE)\n" if control else '') + dependency)
    # Substitute placeholders together: source text is not rescanned.
    import re
    sources = {'DISCOVERY_INPUT_SOURCE': repr(input_source),
               'DISCOVERY_EVIDENCE_SOURCE': repr(evidence_source),
               'WILDCARD_DISCOVERY_SOURCE': repr(discovery_source),
               'WILDCARD_RESULT_SOURCE': repr(result_source)}
    if control:sources['CONTROL_SEQUENCE_SOURCE']=repr(sequence_source)
    template = re.sub('|'.join(sources),
                      lambda match: sources[match.group()], template)
    replace_once("    result=sys.modules['mcp_probe_collect'].collect(sys.argv[7].encode(),inspection_lease_id=sys.argv[8])\n",
                 template)
    if code.count("print('EBASE_MCP_DISPATCH:'") != 1:
        raise ValueError('Exact single dispatch output required')
    compile(code, '<trusted-wildcard-bootstrap>', 'exec')
    return code
