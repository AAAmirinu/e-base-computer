"""Lossy status diagnostics only. Never authorization or server-auth proof."""
import re


def summarize(raw, returncode):
    if not isinstance(raw,bytes) or len(raw)>65536 or type(returncode) is not int:
        raise ValueError('Bounded status bytes and integer returncode required')
    text=raw.decode('utf-8',errors='strict')
    text=re.sub(r'\x1b\[[0-9;]*m','',text)
    lines=[line.strip() for line in text.splitlines() if line.strip()]
    patterns={
        'logged_in_as':r'Logged in as\s+\S.*',
        'not_logged_in':r'Not logged in(?:\..*)?',
        'authenticated_as':r'Authenticated as\s+\S.*',
        'email_label':r'Email:\s*\S.*',
        'account_label':r'Account:\s*\S.*',
        'auth_type_label':r'Auth(?:entication)? [Tt]ype:\s*\S.*',
        'logged_in_label':r'Logged in:\s*\S.*',
    }
    matches={key:sum(bool(re.fullmatch(pattern,line)) for line in lines)
             for key,pattern in patterns.items()}
    return {'returncode':returncode,'line_count':len(lines),'markers':matches,
            'raw_output_suppressed':True,'authentication_verified':False,
            'model_executed':False}


PROBE = r'''
import json,os,selectors,subprocess,sys,time
exec(compile(sys.argv[1],'<trusted-status-shape>','exec'))
child=None
try:
    child=subprocess.Popen(['/home/agent/.local/bin/devin-cli','auth','status'],
        stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    chunks={0:[],1:[]}
    size=0
    deadline=time.monotonic()+20
    with selectors.DefaultSelector() as selector:
        selector.register(child.stdout,selectors.EVENT_READ,0)
        selector.register(child.stderr,selectors.EVENT_READ,1)
        while selector.get_map():
            if time.monotonic()>=deadline:
                raise TimeoutError('Status deadline')
            for event,_ in selector.select(.1):
                chunk=os.read(event.fileobj.fileno(),65536)
                if not chunk:
                    selector.unregister(event.fileobj)
                    continue
                size+=len(chunk)
                if size>65536:
                    raise ValueError('Status output bound')
                chunks[event.data].append(chunk)
    # Never interleave partial stdout/stderr lines into artificial matches.
    streams=[b''.join(chunks[index]) for index in (0,1)]
    code=child.wait(timeout=max(.1,deadline-time.monotonic()))
    result=summarize(streams[0],code)
    other=summarize(streams[1],code)
    result['line_count']+=other['line_count']
    result['markers']={key:count+other['markers'][key] for key,count in result['markers'].items()}
    print('EBASE_AUTH_SHAPE:'+json.dumps(result),flush=True)
finally:
    if child is not None:
        if child.poll() is None:
            child.kill()
        child.wait()
        child.stdout.close()
        child.stderr.close()
'''
