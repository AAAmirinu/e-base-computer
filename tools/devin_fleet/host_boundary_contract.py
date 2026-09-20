"""Pure manager-side sharing contract, not full VM isolation acceptance."""
import re

FIELDS = {'agent', 'auth_mode', 'daemon_uptime', 'daemon_version', 'image',
          'image_digest', 'kits', 'mcp_gateway', 'name', 'network', 'network_policy',
          'proxy', 'runtime_mounts', 'sessions', 'state'}


def validate_host_contract(value, *, name, image_digest, ssh_enabled, clipboard_enabled, mcp):
    if type(image_digest) is not str or re.fullmatch(r'sha256:[0-9a-f]{64}', image_digest) is None:
        raise ValueError('Explicit pinned image digest required')
    # A running sandbox adds informational uptime. It is not a permission,
    # identity or mount field and must not be used as an admission signal.
    if type(value) is not dict or set(value) not in (FIELDS, FIELDS | {'uptime'}):
        raise ValueError('Unknown manager registration schema')
    if (value['name'] != name or value['agent'] != 'devin'
            or value['image'] != 'docker/sandbox-templates:devin-docker'
            or value['image_digest'] != image_digest):
        raise ValueError('Role or image identity changed')
    if type(value['runtime_mounts']) is not list or value['runtime_mounts'] != []:
        raise ValueError('Host runtime mounts prohibited')
    if type(value['kits']) is not list or value['kits'] != []:
        raise ValueError('Additional kits require separate review')
    if ssh_enabled is not False or clipboard_enabled is not False:
        raise ValueError('Explicit sharing restrictions required')
    if (type(mcp) is not dict or set(mcp) != {'servers', 'gateway'}
            or type(mcp['servers']) is not list or mcp['servers'] != []):
        raise ValueError('Known empty MCP server registration required')
    gateway = mcp['gateway']
    if (type(gateway) is not dict or set(gateway) != {'decision','local','name','operator','signed_in_as'}
            or gateway['local'] is not True or gateway['decision'] != 'local'):
        raise ValueError('Known local MCP gateway state required')
    # This does not attest gateway disablement, credential absence, VM kernel,
    # text clipboard fencing, or guest policy. Caller must check those separately.
