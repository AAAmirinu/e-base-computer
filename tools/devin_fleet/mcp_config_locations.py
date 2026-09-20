"""Fixed metadata-only configuration inventory; never opens file contents."""
import os
from pathlib import Path
import stat

PATHS = {
    'user_main': '/home/agent/.config/devin/config.json',
    'user_mcp': '/home/agent/.config/devin/mcp_config.json',
    'user_rules': '/home/agent/.config/devin/AGENTS.md',
    'user_skills': '/home/agent/.config/devin/skills',
    'home_project': '/home/agent/.devin',
    'tmp_project': '/tmp/.devin',
    'root_project': '/.devin',
    'tmp_git': '/tmp/.git',
    'root_git': '/.git',
    'tmp_jj': '/tmp/.jj',
    'root_jj': '/.jj',
    'system_devin': '/etc/devin/system.json',
}
KINDS = {'missing', 'regular', 'directory', 'symlink', 'other', 'inaccessible'}
ENV_KEYS = ('XDG_CONFIG_HOME', 'XDG_CONFIG_DIRS', 'DEVIN_CONFIG_DIR', 'DEVIN_CONFIG_PATH')


def collect():
    records = {}
    for label, path in PATHS.items():
        try:
            mode = Path(path).lstat().st_mode
            kind = ('symlink' if stat.S_ISLNK(mode) else 'regular' if stat.S_ISREG(mode)
                    else 'directory' if stat.S_ISDIR(mode) else 'other')
        except FileNotFoundError:
            kind = 'missing'
        except OSError:
            kind = 'inaccessible'
        records[label] = kind
    return dict(paths=records, environment_present={key:key in os.environ for key in ENV_KEYS},
                home_is_expected=os.environ.get('HOME') == '/home/agent',
                file_contents_read=False, model_executed=False, configuration_isolated=False)


def validate(value):
    if (type(value) is not dict or set(value) != {'paths','environment_present','home_is_expected',
            'file_contents_read','model_executed','configuration_isolated'}
            or type(value['paths']) is not dict or set(value['paths']) != set(PATHS)
            or any(type(kind) is not str or kind not in KINDS for kind in value['paths'].values())
            or type(value['environment_present']) is not dict or set(value['environment_present']) != set(ENV_KEYS)
            or any(type(flag) is not bool for flag in value['environment_present'].values())
            or type(value['home_is_expected']) is not bool
            or any(value[key] is not False for key in ('file_contents_read','model_executed','configuration_isolated'))):
        raise ValueError('Invalid fixed configuration metadata')
    return value


PROBE = "import json,sys,types; module=types.ModuleType('fixed_config_locations'); exec(sys.argv[1],module.__dict__); print('EBASE_MCP_LOCATIONS:'+json.dumps(module.collect()))"
