"""Finite unauthenticated reachability observations inside an owned network window.

No standalone entry point or permission changes. HTTP status is not catalog,
authentication, model, or fleet acceptance. Never returns response content.
"""
import json
from mcp_probe_catalog import _capture, CaptureDeadline

HOSTS=('api.devin.ai','app.devin.ai','server.codeium.com','unleash.codeium.com')
ERRORS=frozenset(('tls','timeout','dns','connection','http','other','capture_deadline'))
PROBE=r'''
import os
os.environ.clear()
import sys,json,ssl,socket,http.client
hosts=('api.devin.ai','app.devin.ai','server.codeium.com','unleash.codeium.com')
if len(sys.argv)!=2 or sys.argv[1] not in hosts:
    raise ValueError('Fixed endpoint required')
host=sys.argv[1]
status=None
error=None
connection=None
try:
    connection=http.client.HTTPSConnection(host,443,timeout=5,context=ssl.create_default_context())
    connection.request('HEAD','/',headers={'Connection':'close'})
    response=connection.getresponse()
    status=response.status
    if type(status) is not int or not 100<=status<=599:
        status=None
        error='http'
except ssl.SSLError: error='tls'
except TimeoutError: error='timeout'
except socket.gaierror: error='dns'
except OSError: error='connection'
except http.client.HTTPException: error='http'
except Exception: error='other'
finally:
    if connection is not None: connection.close()
print(json.dumps({'host':host,'status':status,'error_class':error}))
'''


def _pairs(items):
    result={}
    for key,value in items:
        if key in result: raise ValueError('Duplicate endpoint result key')
        result[key]=value
    return result


def validate(value,host):
    if type(host) is not str or host not in HOSTS:
        raise ValueError('Fixed endpoint required')
    if (type(value) is not dict or set(value)!={'host','status','error_class'}
            or value['host']!=host):
        raise ValueError('Exact endpoint result required')
    status,error=value['status'],value['error_class']
    if error is None:
        if type(status) is not int or not 100<=status<=599:
            raise ValueError('Finite HTTP status required')
    elif type(error) is not str or error not in ERRORS or status is not None:
        raise ValueError('Finite endpoint error required')
    return dict(value)


def probe_endpoints():
    """Caller owns the fixed four-host window; total four captures, no retries."""
    results=[]
    for host in HOSTS:
        try:
            raw,code=_capture(['/usr/bin/python3','-I','-c',PROBE,host],'/',timeout=6)
        except CaptureDeadline:
            value={'host':host,'status':None,'error_class':'capture_deadline'}
        else:
            if type(code) is not int or code!=0 or type(raw) is not bytes or len(raw)>512:
                raise ValueError('Bounded endpoint subprocess receipt required')
            try: value=json.loads(raw,object_pairs_hook=_pairs)
            except (ValueError,UnicodeError): raise ValueError('Invalid endpoint receipt') from None
        results.append(validate(value,host))
    return results
