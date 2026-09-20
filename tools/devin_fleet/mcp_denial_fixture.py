"""Trusted synthetic stdio MCP fixture. No files, environment, sockets or exec.

Run only in the role VM under the bounded maintenance supervisor. This server
never reflects arbitrary request strings; even errors use fixed messages.
"""
import json
import sys

MARKER = 'EBASE_MCP_FIXTURE_CALLED'
VERSIONS = ('2024-11-05', '2025-03-26', '2025-06-18', '2025-11-25')


def reply(request):
    if type(request) is not dict or request.get('jsonrpc') != '2.0':
        raise ValueError('Invalid protocol request')
    if 'id' not in request:
        return None
    identity = request['id']
    if type(identity) is not int or not 0 <= identity <= 2**53-1:
        raise ValueError('Bounded numeric request id required')
    method, params = request.get('method'), request.get('params', {})
    result = None
    if method == 'initialize' and type(params) is dict:
        version = params.get('protocolVersion')
        result = dict(protocolVersion=version if version in VERSIONS else VERSIONS[0],
                      capabilities={'tools': {}}, serverInfo={'name':'fleet-probe','version':'1.0.0'})
    elif method == 'ping':
        result = {}
    elif method == 'tools/list':
        result = {'tools':[{'name':'echo','description':'Return one fixed synthetic test marker.',
            'inputSchema':{'type':'object','properties':{},'additionalProperties':False}}]}
    elif method == 'tools/call' and params == {'name':'echo','arguments':{}}:
        result = {'content':[{'type':'text','text':MARKER}], 'isError':False}
    if result is None:
        return {'jsonrpc':'2.0','id':identity,'error':{'code':-32602,'message':'Unsupported fixed probe request'}}
    return {'jsonrpc':'2.0','id':identity,'result':result}


def serve(source, sink, record_event=None):
    # Supervisor owns lifetime. Bounds prevent unbounded input or reflection.
    for _ in range(64):
        line = source.readline(65537)
        if not line:
            return
        if len(line)>65536:
            raise ValueError('Protocol input limit')
        request = json.loads(line)
        # The optional trusted supervisor sink receives fixed tokens only.
        # Any tool invocation is disqualifying, even malformed/unsupported ones.
        if record_event is not None and type(request) is dict and request.get('method') == 'tools/call':
            record_event('called')
        response = reply(request)
        if response is not None:
            sink.write(json.dumps(response)+'\n')
            sink.flush()
            if record_event is not None and 'result' in response:
                if request.get('method') == 'initialize': record_event('initialized')
                if request.get('method') == 'tools/list': record_event('listed')


if __name__=='__main__':
    serve(sys.stdin, sys.stdout)
