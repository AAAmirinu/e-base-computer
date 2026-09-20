"""Read fixed public CLI binary text only; never execute CLI or read settings."""
import hashlib
import os
from mcp_cli_identity import verify_cli, CLI, PIN

MARKERS = ('Permission to call', 'access for this MCP server')


def inspect():
    verify_cli()
    with open(os.path.realpath(CLI,strict=True),'rb') as stream:
        raw=stream.read(256*1024*1024+1)
    if len(raw)>256*1024*1024 or hashlib.sha256(raw).hexdigest()!=PIN:
        raise ValueError('Fixed CLI bytes required')
    contexts=[]
    for marker in MARKERS:
        offset=raw.find(marker.encode())
        if offset>=0:
            chunk=raw[max(0,offset-700):offset+len(marker)+1000]
            contexts.append(dict(marker=marker,context=''.join(chr(c) if 32<=c<127 else ' ' for c in chunk)))
    return validate(dict(binary_sha256=PIN,contexts=contexts,cli_executed=False,model_executed=False))


def validate(value):
    if (type(value) is not dict or set(value)!={'binary_sha256','contexts','cli_executed','model_executed'}
            or value['binary_sha256']!=PIN or value['cli_executed'] is not False
            or value['model_executed'] is not False or type(value['contexts']) is not list
            or len(value['contexts'])>len(MARKERS)):
        raise ValueError('Fixed static policy evidence required')
    seen=set()
    for item in value['contexts']:
        if (type(item) is not dict or set(item)!={'marker','context'} or item['marker'] not in MARKERS
                or item['marker'] in seen or type(item['context']) is not str
                or not 0<len(item['context'])<=1750 or any(not 32<=ord(c)<127 for c in item['context'])):
            raise ValueError('Bounded static context required')
        seen.add(item['marker'])
    return value


PROBE="""import sys,json,types
identity=types.ModuleType('mcp_cli_identity');sys.modules['mcp_cli_identity']=identity
exec(sys.argv[1],identity.__dict__)
scope={};exec(sys.argv[2],scope)
print('EBASE_CLI_POLICY:'+json.dumps(scope['inspect']()))
"""
