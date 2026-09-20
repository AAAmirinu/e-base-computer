"""Parse two fixed configuration files in the guest; export counts, never values."""
import json
import os
import stat


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate configuration key')
        result[key] = value
    return result


def summarize(raw):
    if type(raw) is not bytes or not 0 < len(raw) <= 65536:
        raise ValueError('Bounded config required')
    def reject(value):
        raise ValueError('Invalid JSON constant')
    value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=reject)
    if type(value) is not dict:
        raise ValueError('Configuration object required')
    servers = value.get('mcpServers', {})
    if type(servers) is not dict or len(servers) > 256 or any(type(s) is not dict for s in servers.values()):
        raise ValueError('Bounded server map required')
    for server in servers.values():
        if ('disabled' in server and type(server['disabled']) is not bool
                or 'command' in server and 'url' in server
                or any(key in server and (type(server[key]) is not str or not server[key])
                       for key in ('command','url'))):
            raise ValueError('Invalid server shape')
    hooks = value.get('hooks', {})
    hook_state = ('absent' if 'hooks' not in value else 'invalid' if type(hooks) is not dict
                  else 'nonempty' if hooks else 'empty')
    return dict(status='parsed', server_count=len(servers),
                disabled_count=sum(s.get('disabled') is True for s in servers.values()),
                stdio_count=sum('command' in s for s in servers.values()),
                remote_count=sum('url' in s for s in servers.values()),
                hooks=hook_state)


def collect(*, diagnostic=False):
    # Diagnostic parsing is not acceptance for execution. Strict mode is unchanged.
    if type(diagnostic) is not bool:
        raise ValueError('Boolean diagnostic mode required')
    result = {}
    parent = None
    try:
        parent = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
        for component in ('home', 'agent', '.config', 'devin'):
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.close(parent)
            parent = child
        for label, name in (('main', 'config.json'), ('mcp', 'mcp_config.json')):
            stage = 'open'
            try:
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
                try:
                    before = os.fstat(fd)
                    stage = 'metadata'
                    checks = dict(regular=stat.S_ISREG(before.st_mode), owner_expected=before.st_uid in (0, os.getuid()),
                                  single_link=before.st_nlink == 1, protected=not bool(before.st_mode & 0o022),
                                  bounded=before.st_size <= 65536)
                    required = [flag for key, flag in checks.items() if key != 'protected' or not diagnostic]
                    if not all(required):
                        result[label] = {'status':'unverified','stage':'metadata','checks':checks}
                        continue
                    stage = 'read'
                    with os.fdopen(os.dup(fd), 'rb') as stream:
                        raw = stream.read(65537)
                    after = os.fstat(fd)
                    linked = os.stat(name, dir_fd=parent, follow_symlinks=False)
                    fields = lambda s: (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_mode,s.st_nlink)
                    if fields(before) != fields(after) or fields(after) != fields(linked):
                        stage = 'changed'
                        raise ValueError('Configuration changed')
                    stage = 'parse'
                    result[label] = summarize(raw)
                    if not checks['protected']:
                        result[label]['status'] = 'parsed_untrusted'
                finally:
                    os.close(fd)
            except Exception:
                result[label] = {'status': 'unverified', 'stage': stage}
    except Exception:
        result = {key:{'status':'unverified'} for key in ('main','mcp')}
    finally:
        if parent is not None:
            os.close(parent)
    return dict(files=result, raw_values_exported=False, model_executed=False, configuration_isolated=False)


def validate(value):
    if (type(value) is not dict or set(value) != {'files','raw_values_exported','model_executed','configuration_isolated'}
            or any(value[key] is not False for key in ('raw_values_exported','model_executed','configuration_isolated'))
            or type(value['files']) is not dict or set(value['files']) != {'main','mcp'}):
        raise ValueError('Invalid configuration summary')
    for record in value['files'].values():
        if record == {'status':'unverified'}:
            continue
        if (type(record) is dict and set(record)=={'status','stage','checks'} and record['status']=='unverified'
                and record['stage']=='metadata' and type(record['checks']) is dict
                and set(record['checks'])=={'regular','owner_expected','single_link','protected','bounded'}
                and all(type(flag) is bool for flag in record['checks'].values())):
            continue
        if (type(record) is dict and set(record)=={'status','stage'} and record['status']=='unverified'
                and type(record['stage']) is str and record['stage'] in ('open','metadata','read','changed','parse')):
            continue
        if (type(record) is not dict or set(record) != {'status','server_count','disabled_count','stdio_count','remote_count','hooks'}
                or record['status'] not in ('parsed','parsed_untrusted') or type(record['hooks']) is not str
                or record['hooks'] not in ('absent','empty','nonempty','invalid')
                or any(type(record[k]) is not int or not 0<=record[k]<=256
                       for k in ('server_count','disabled_count','stdio_count','remote_count'))
                or any(record[k]>record['server_count'] for k in ('disabled_count','stdio_count','remote_count'))):
            raise ValueError('Invalid fixed counters')
    return value


PROBE = "import json,sys,types; module=types.ModuleType('fixed_config_shape'); exec(sys.argv[1],module.__dict__); print('EBASE_MCP_SHAPE:'+json.dumps(module.collect(diagnostic=True)))"
