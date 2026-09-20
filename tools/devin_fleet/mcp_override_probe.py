"""Offline installed-CLI configuration experiment, never a model/permission test."""
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile

CLI='/home/agent/.local/bin/devin-cli'
WORDS=frozenset(('command','disabled','enabled','true','false','project','user','local','stdio','http',
                 'url','transport','scope','source','name','server','servers','mcp','configuration','config','type','status','by'))
PUNCT={':':'colon','(':'open_paren',')':'close_paren','[':'open_bracket',']':'close_bracket','=':'equals'}


def display_tokens(raw, names):
    """A finite vocabulary only; no arbitrary names, values or characters escape."""
    text=re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]','',raw.decode('utf-8',errors='replace'))
    if len(text)>65536 or len(text.splitlines())>32: raise ValueError('Display bound')
    names=sorted(names,key=len,reverse=True)
    pattern='|'.join([r'/usr/bin/false',*(re.escape(name) for name in names),r'[A-Za-z_][A-Za-z_0-9-]*',r'[^\s]'])
    lines=[]
    for line in text.splitlines():
        tokens=[]
        for match in re.finditer(pattern,line):
            token=match.group()
            category=('false_command' if token=='/usr/bin/false' else
                      'fixture_name' if token=='fleet-probe' and token in names else
                      'inherited_name' if token in names else
                      'word_'+token.lower() if token.lower() in WORDS else PUNCT.get(token,'unknown'))
            if category!='unknown' or not tokens or tokens[-1]!='unknown': tokens.append(category)
            if len(tokens)>64: raise ValueError('Token bound')
        lines.append(tokens)
    return lines


def pairs(items):
    result={}
    for key,value in items:
        if key in result: raise ValueError('Duplicate key')
        result[key]=value
    return result


def read_global(name):
    if name not in ('config.json','mcp_config.json'): raise ValueError('Fixed config only')
    parent=os.open('/',os.O_RDONLY|os.O_DIRECTORY)
    try:
        for component in ('home','agent','.config','devin'):
            child=os.open(component,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent)
            os.close(parent)
            parent=child
        fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
        try:
            before=os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or before.st_uid not in (0,os.getuid()) or before.st_size>65536:
                raise ValueError('Fixed bounded config required')
            with os.fdopen(os.dup(fd),'rb') as stream: raw=stream.read(65537)
            stamp=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_mode)
            if stamp(before)!=stamp(os.fstat(fd)) or stamp(before)!=stamp(os.stat(name,dir_fd=parent,follow_symlinks=False)):
                raise ValueError('Config changed')
            return raw
        finally: os.close(fd)
    finally: os.close(parent)


def overrides(raw):
    value=json.loads(raw,object_pairs_hook=pairs)
    servers=value.get('mcpServers') if type(value) is dict else None
    if (type(servers) is not dict or not 0<len(servers)<=16 or 'fleet-probe' in servers
            or any(type(name) is not str or re.fullmatch(r'[A-Za-z0-9_.-]{1,64}',name) is None for name in servers)):
        raise ValueError('Bounded named servers required')
    result={name:{'command':'/usr/bin/false','disabled':True} for name in servers}
    result['fleet-probe']={'command':'/usr/bin/false','disabled':False}
    return result


def exact_get_display(raw, name, disabled):
    if type(name) is not str or type(disabled) is not bool or b'\x1b' in raw:
        return False
    try: lines=[line.strip(' ') for line in raw.decode('utf-8').splitlines()]
    except UnicodeError: return False
    expected=['Server: '+name,'Command: /usr/bin/false']
    if not disabled: return lines==expected
    return (len(lines)==3 and lines[0]==expected[0] and lines[2]==expected[1]
            and re.fullmatch(r'Status: [Dd]isabled [—–-] [Dd]isabled by [Uu]ser',lines[1]) is not None)


def shape(raw, code, names=(), requested_name=None, expect_disabled=None):
    if len(raw)>65536: raise ValueError('Output bound')
    result=dict(returncode=code,json_object=False,root_disabled_true=False,
                root_disabled_false=False,root_false_command=False,line_count=len(raw.splitlines()),
                display_tokens=display_tokens(raw,names),
                exact_get_override_display=code==0 and exact_get_display(raw,requested_name,expect_disabled))
    try: value=json.loads(raw,object_pairs_hook=pairs)
    except (ValueError,UnicodeError): return result
    if type(value) is dict:
        result.update(json_object=True,root_disabled_true=value.get('disabled') is True,
                      root_disabled_false=value.get('disabled') is False,
                      root_false_command=value.get('command')=='/usr/bin/false')
    return result


def collect():
    result={'model_executed':False,'override_verified':False,'raw_values_exported':False,
            'global_config_unchanged':False,'commands':[],'status':'unverified'}
    try:
        originals={name:read_global(name) for name in ('config.json','mcp_config.json')}
        main=json.loads(originals['config.json'],object_pairs_hook=pairs)
        if type(main) is not dict or main.get('hooks',{})!={} or main.get('mcpServers',{})!={}:
            raise ValueError('No hooks or pending migration required')
        servers=overrides(originals['mcp_config.json'])
        work=Path(tempfile.mkdtemp(prefix='e-base-mcp-override-',dir='/tmp'))
        for directory in ('.devin','.git','.git/refs','.git/refs/heads','.git/objects'):
            (work/directory).mkdir(mode=0o700)
        def write(name,raw):
            fd=os.open(work/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'wb') as stream: stream.write(raw)
        write('.git/HEAD',b'ref: refs/heads/probe\n')
        write('.git/config',b'[core]\nrepositoryformatversion = 0\nbare = false\n')
        write('.devin/mcp_config.json',json.dumps({'mcpServers':servers}).encode())
        write('config.json',json.dumps({'version':1,'read_config_from':{'cursor':False,'windsurf':False,'claude':False},
                                      'permissions':{'deny':['read','write','edit','exec','mcp__*'],'allow':[]}}).encode())
        for label,args in [('list',['mcp','list']),('fixture',['mcp','get','fleet-probe']),
                           ('inherited',['mcp','get',next(name for name in servers if name!='fleet-probe')])]:
            proc=subprocess.run([CLI,'--config',str(work/'config.json'),*args],cwd=work,
                                stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                                timeout=5,close_fds=True,umask=0o077)
            result['commands'].append(dict(label=label,**shape(proc.stdout,proc.returncode,tuple(servers),
                args[2] if label!='list' else None,label=='inherited' if label!='list' else None)))
        result['global_config_unchanged']=all(read_global(name)==raw for name,raw in originals.items())
        result['status']='observed'
    except Exception:
        result['status']='unverified'
    return result


PROBE="import json,sys,types; module=types.ModuleType('fixed_mcp_override'); exec(sys.argv[1],module.__dict__); print('EBASE_MCP_OVERRIDE:'+json.dumps(module.collect()))"


def validate(value):
    if (type(value) is not dict or set(value)!={'model_executed','override_verified','raw_values_exported','global_config_unchanged','commands','status'}
            or any(value[k] is not False for k in ('model_executed','override_verified','raw_values_exported'))
            or type(value['global_config_unchanged']) is not bool or value['status'] not in ('observed','unverified')
            or type(value['commands']) is not list or len(value['commands'])>3):
        raise ValueError('Invalid override observation')
    for item in value['commands']:
        if (type(item) is not dict or set(item)!={'label','returncode','json_object','root_disabled_true','root_disabled_false','root_false_command','line_count','display_tokens','exact_get_override_display'}
                or item['label'] not in ('list','fixture','inherited') or type(item['returncode']) is not int
                or type(item['line_count']) is not int or not 0<=item['line_count']<=65536
                or any(type(item[k]) is not bool for k in ('json_object','root_disabled_true','root_disabled_false','root_false_command','exact_get_override_display'))):
            raise ValueError('Invalid command observation')
        vocabulary={'unknown','false_command','fixture_name','inherited_name'}|set(PUNCT.values())|{'word_'+word for word in WORDS}
        if (type(item['display_tokens']) is not list or len(item['display_tokens'])>32
                or any(type(line) is not list or len(line)>64 or any(type(token) is not str or token not in vocabulary for token in line)
                       for line in item['display_tokens'])):
            raise ValueError('Invalid fixed display tokens')
    return value
