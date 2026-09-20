"""Pure validation-container specification. Does not call Docker or run source.

Create first, inspect before start, then run trusted in-container boundary
probes before source admission. An inspect match alone is not isolation proof.
The lifecycle owner must retain exact container ID and stop it on every exit.
"""
import re


ENV = ['PATH=/usr/local/bin:/usr/bin:/bin', 'HOME=/work', 'LANG=C.UTF-8']
COMMAND = ['-i', *ENV, '/usr/local/bin/python3', '-I', '-c',
           'import time; time.sleep(3600)']
TMPFS = {'/work': 'rw,nosuid,nodev,size=128m,uid=65532,gid=65532,mode=700',
         '/tmp': 'rw,nosuid,nodev,noexec,size=64m,mode=1777'}
LABEL = 'e-base.validation.operation'


def _identity(image_id, operation):
    if not isinstance(image_id, str) or re.fullmatch('sha256:[0-9a-f]{64}', image_id) is None:
        raise ValueError('Pinned local image ID required; tags cannot be used')
    if not isinstance(operation, str) or re.fullmatch('[0-9a-f]{32}', operation) is None:
        raise ValueError('Canonical validation operation required')


def admit_image(image):
    """Check trusted Docker image inspect object; never accept agent templates.

    Image provenance/digest approval is a separate caller gate. Restrict ambient
    environment before env -i runs: e.g. LD_PRELOAD must not affect entrypoint.
    """
    if not isinstance(image, dict):
        raise ValueError('Image inspect object required')
    _identity(image.get('Id'), '0' * 32)
    config = image.get('Config')
    if (image.get('Os') != 'linux' or image.get('Architecture') != 'amd64' or
            not isinstance(config, dict)):
        raise ValueError('Unsupported image platform/configuration')
    for key in ('Volumes', 'ExposedPorts', 'OnBuild'):
        if config.get(key):
            raise ValueError('Image requests implicit runtime resources')
    values = config.get('Env')
    if not isinstance(values, list):
        raise ValueError('Explicit image environment required')
    seen = set()
    for value in values:
        if not isinstance(value, str) or '=' not in value:
            raise ValueError('Invalid image environment')
        key, _ = value.split('=', 1)
        if key not in ('PATH', 'LANG', 'PYTHON_VERSION', 'PYTHON_SHA256', 'GPG_KEY') or key in seen:
            raise ValueError('Unexpected image environment key')
        seen.add(key)
    return image['Id']


def create_arguments(image_id, operation):
    _identity(image_id, operation)
    return ['docker', 'create', '--pull', 'never', '--name', 'e-base-check-' + operation,
            '--label', LABEL + '=' + operation, '--network', 'none', '--ipc', 'private',
            '--runtime', 'runc', '--user', '65532:65532', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges=true', '--read-only',
            '--cpus', '1', '--memory', '512m', '--memory-swap', '512m',
            '--pids-limit', '64', '--ulimit', 'nofile=256:256',
            '--restart', 'no', '--no-healthcheck', '--workdir', '/work',
            '--log-driver', 'local', '--log-opt', 'max-size=1m', '--log-opt', 'max-file=1',
            '--log-opt', 'compress=false',
            '--tmpfs', '/work:' + TMPFS['/work'], '--tmpfs', '/tmp:' + TMPFS['/tmp'],
            '--entrypoint', '/usr/bin/env', image_id, *COMMAND]


def verify_created_container(info, image_id, operation):
    """Fail closed on requested isolation mismatches in docker inspect JSON."""
    _identity(image_id, operation)
    if not isinstance(info, dict):
        raise ValueError('Container inspect object required')
    container_id = info.get('Id')
    if not isinstance(container_id, str) or re.fullmatch('[0-9a-f]{64}', container_id) is None:
        raise ValueError('Invalid container ID')
    if info.get('Image') != image_id or info.get('Name') != '/e-base-check-' + operation:
        raise ValueError('Container identity mismatch')
    config, host, state = (info.get(k) for k in ('Config', 'HostConfig', 'State'))
    if not all(isinstance(v, dict) for v in (config, host, state)):
        raise ValueError('Incomplete container inspect')
    if state.get('Status') != 'created' or state.get('Running') is not False:
        raise ValueError('Container has already started')
    if (config.get('User') != '65532:65532' or config.get('WorkingDir') != '/work' or
            config.get('Entrypoint') != ['/usr/bin/env'] or config.get('Cmd') != COMMAND or
            config.get('Labels', {}).get(LABEL) != operation or
            config.get('Healthcheck', {}).get('Test') != ['NONE']):
        raise ValueError('Container command/config mismatch')
    admit_image({'Id': image_id, 'Os': 'linux', 'Architecture': 'amd64', 'Config': config})
    expected = {'NetworkMode': 'none', 'Privileged': False, 'ReadonlyRootfs': True,
                'CapDrop': ['ALL'], 'SecurityOpt': ['no-new-privileges=true'],
                'Memory': 512 * 1024 * 1024, 'MemorySwap': 512 * 1024 * 1024,
                'NanoCpus': 1000000000, 'PidsLimit': 64, 'Tmpfs': TMPFS, 'Runtime': 'runc',
                'RestartPolicy': {'Name': 'no', 'MaximumRetryCount': 0},
                'LogConfig': {'Type': 'local', 'Config': {'max-size': '1m', 'max-file': '1', 'compress': 'false'}},
                'Ulimits': [{'Name': 'nofile', 'Hard': 256, 'Soft': 256}]}
    for key, value in expected.items():
        if key not in host or type(host[key]) is not type(value) or host[key] != value:
            raise ValueError('Container isolation mismatch: ' + key)
    for key in ('Binds', 'Mounts', 'VolumesFrom', 'Devices', 'DeviceRequests', 'CapAdd',
                'GroupAdd', 'PortBindings', 'ExtraHosts', 'Links', 'Dns', 'DnsSearch', 'DeviceCgroupRules'):
        if host.get(key):
            raise ValueError('Unexpected container resource: ' + key)
    if host.get('PidMode') not in ('', 'private') or host.get('IpcMode') != 'private':
        raise ValueError('Shared process/IPC namespace refused')
    if host.get('UTSMode') != '' or host.get('UsernsMode') not in ('', 'private'):
        raise ValueError('Shared UTS/user namespace refused')
    if info.get('Mounts') != []:
        raise ValueError('Unexpected persistent mount')
    networking = info.get('NetworkSettings')
    if (not isinstance(networking, dict) or not isinstance(networking.get('Networks'), dict) or
            set(networking['Networks']) != {'none'}):
        raise ValueError('Unexpected network attachment')
    return container_id
