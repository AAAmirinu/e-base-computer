"""Trusted guest-only presence checks; never read credentials or execute source."""
import json
import os
from pathlib import Path
import shutil
import sys
import urllib.error
import urllib.request

paths = ('/home/agent/.local/share/devin/credentials.toml', '/home/agent/.ssh',
         '/home/agent/.config/gh/hosts.yml', '/mnt/c', '/mnt/f', '/host',
         '/host_mnt', '/run/sandbox/source')
keys = ('DEVIN_API_KEY', 'OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'GH_TOKEN',
        'GITHUB_TOKEN', 'SSH_AUTH_SOCK')
mounts = Path('/proc/self/mountinfo').read_text().splitlines()
result = {'uid': os.getuid(), 'python': sys.version.split()[0],
          'commands_present': {k: shutil.which(k) is not None for k in ('python3', 'git', 'node', 'devin', 'devin-cli')},
          'sensitive_paths_present': {p: os.path.lexists(p) for p in paths},
          'credential_variables_present': {k: k in os.environ for k in keys},
          'shared_fs_mounts': [m for m in mounts if any(' - ' + fs + ' ' in m for fs in ('9p', 'virtiofs', 'cifs', 'drvfs'))]}
try:
    with urllib.request.urlopen('https://example.com', timeout=8) as response:
        result['network_probe'] = {'unexpected_response': response.status}
except urllib.error.HTTPError as error:
    result['network_probe'] = {'http_status': error.code}
except Exception as error:
    result['network_probe'] = {'error_type': type(error).__name__}
print(json.dumps(result), flush=True)
