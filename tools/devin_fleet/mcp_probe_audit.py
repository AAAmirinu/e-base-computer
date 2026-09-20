"""Fixed-token fixture telemetry. No tool args, identity, or credential values.

An audit belongs to one supervisor-reserved private guest directory. It is not
an independent security attestation or proof of the identity of a CLI session.
"""
import os
from pathlib import PurePosixPath
import re
import stat

EVENTS = frozenset(('initialized','listed','called'))


def open_audit(path, *, expected_identity=None):
    if type(path) is not str:
        raise ValueError('Exact audit path string required')
    original=path
    path = PurePosixPath(path)
    if (str(path) != original or len(path.parts)!=4 or path.parts[:2]!=('/','tmp')
            or re.fullmatch(r'e-base-mcp-probe-[a-z0-9_]{8}',path.parts[2]) is None
            or path.name!='fixture-events.log'):
        raise ValueError('Fixed private probe audit path required')
    parent=os.open(str(path.parent),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        info=os.fstat(parent)
        if info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o700:
            raise ValueError('Private owned audit directory required')
        fd=os.open(path.name,os.O_WRONLY|os.O_APPEND|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
    finally:
        os.close(parent)
    try:
        info=os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1
                or stat.S_IMODE(info.st_mode)!=0o600 or info.st_size>4096):
            raise ValueError('Bounded private audit file required')
        if expected_identity is not None and (
                type(expected_identity) is not tuple or len(expected_identity)!=2
                or any(type(n) is not int or n<0 for n in expected_identity)
                or (info.st_dev,info.st_ino)!=expected_identity):
            raise ValueError('Reserved audit inode changed')
        return fd
    except BaseException:
        os.close(fd)
        raise


def record_event(fd, event):
    if type(event) is not str or event not in EVENTS:
        raise ValueError('Fixed audit event required')
    raw=(event+'\n').encode('ascii')
    if os.fstat(fd).st_size+len(raw)>1024:
        raise ValueError('Audit size limit')
    if os.write(fd,raw)!=len(raw):
        raise RuntimeError('Incomplete audit event')
    os.fsync(fd)


def summarize_audit(raw):
    if type(raw) is not bytes or len(raw)>1024:
        raise ValueError('Bounded audit bytes required')
    lines=raw.decode('ascii').splitlines()
    if any(line not in EVENTS for line in lines) or (raw and not raw.endswith(b'\n')):
        raise ValueError('Unknown or partial audit event')
    ordered=('initialized' in lines and 'listed' in lines
             and lines.index('initialized')<lines.index('listed'))
    return dict(initialization_count=lines.count('initialized'),
                tool_list_count=lines.count('listed'), tool_call_count=lines.count('called'),
                discovery_sequence_observed=ordered, cli_session_bound=False)


def record_nonce_event(fd, nonce, event):
    if type(nonce) is not str or re.fullmatch('[0-9a-f]{32}',nonce) is None:
        raise ValueError('Fixed attempt nonce required')
    if type(event) is not str or event not in EVENTS:
        raise ValueError('Fixed audit event required')
    raw=(nonce+':'+event+'\n').encode('ascii')
    if os.fstat(fd).st_size+len(raw)>4096:
        raise ValueError('Audit size limit')
    if os.write(fd,raw)!=len(raw):
        raise RuntimeError('Incomplete audit event')
    os.fsync(fd)


def summarize_nonce_audit(raw, expected_nonce):
    if (type(expected_nonce) is not str or re.fullmatch('[0-9a-f]{32}',expected_nonce) is None
            or type(raw) is not bytes or not 0<len(raw)<=4096 or not raw.endswith(b'\n')):
        raise ValueError('Bounded attempt audit required')
    lines=raw.decode('ascii').splitlines()
    if not 1<=len(lines)<=64:
        raise ValueError('Audit event limit')
    events=[]
    for line in lines:
        nonce,separator,event=line.partition(':')
        if not separator or nonce!=expected_nonce or event not in EVENTS:
            raise ValueError('Audit attempt mismatch')
        events.append(event)
    result=summarize_audit(('\n'.join(events)+'\n').encode('ascii'))
    result['attempt_nonce_verified']=True
    return result
