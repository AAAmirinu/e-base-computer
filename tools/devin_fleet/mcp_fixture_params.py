"""Offline versioned no-argument echo protocol adapter; no live activation.

Original ID-only compatibility inputs remain unchanged. Metadata is bounded,
ignored, never reflected, and never grants task or other tool execution.
"""
import hashlib
from mcp_fixture_compat import adapt_inputs as id_inputs

OLD="    elif method == 'tools/call' and params == {'name':'echo','arguments':{}}:"
NEW="    elif method == 'tools/call' and _empty_echo_params(params):"
HELPER='''
def _empty_echo_params(params):
    if (type(params) is not dict or set(params)-{'name','arguments','_meta'}
            or params.get('name')!='echo' or type(params.get('arguments',{})) is not dict
            or params.get('arguments',{})!={} or type(params.get('_meta',{})) is not dict):
        return False
    try:
        encoded=json.dumps(params.get('_meta',{}),allow_nan=False,ensure_ascii=True)
    except (TypeError,ValueError,RecursionError):
        return False
    return len(encoded.encode('ascii'))<=1024

'''

def adapt_inputs(inputs):
    base=id_inputs(inputs)
    raw=base['fixture.py'];source=raw.decode('utf-8')
    if source.count(OLD)!=1 or source.count('def reply(request):')!=1:
        raise ValueError('Trusted params guard drift')
    updated=source.replace(OLD,NEW,1).replace('def reply(request):',HELPER+'def reply(request):',1).encode()
    if len(updated)>16384:raise ValueError('Fixture source limit')
    compile(updated,'<trusted-params-fixture>','exec')
    digest=hashlib.sha256(raw).hexdigest().encode()
    if base['runner.py'].count(digest)!=1:raise ValueError('Exact ID fixture binding required')
    runner=base['runner.py'].replace(digest,hashlib.sha256(updated).hexdigest().encode(),1)
    return dict(base,**{'fixture.py':updated,'runner.py':runner})
