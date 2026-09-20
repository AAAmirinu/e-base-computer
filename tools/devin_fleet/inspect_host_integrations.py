"""Fixed read-only manager settings inventory; no VM start or secret output."""
import json
import re
import tempfile

from durable import atomic_write_json
from interactive_machine_auth import run
from managed_cli_guard import require_managed_namespace
from sandbox_capacity_probe import ROOT, inventory
from sandbox_runtime import SandboxRuntime
from validation_dispatch_receipt import _pairs
from validation_snapshot_input import _file

SETTINGS = ('ssh.agentForwardingEnabled', 'clipboard.imagePaste')
MCP_METADATA_FIELDS = ('gateway', 'gateways', 'errors', 'warnings', 'version',
                       'schema_version', 'metadata', 'catalog', 'auth', 'status')
INSPECT_FIELDS = ('id', 'name', 'agent', 'sandbox', 'config', 'configuration', 'runtime',
                  'kit', 'kits', 'kit_ref', 'kit_refs', 'kit_config', 'image', 'template',
                  'credentials', 'secrets', 'custom_secrets', 'oauth', 'apiKey',
                  'passthrough', 'proxyManaged', 'env', 'environment', 'mounts',
                  'workspace', 'workspaces', 'mcp', 'settings', 'ssh', 'display',
                  'runtime_mounts', 'source', 'target', 'destination', 'read_only',
                  'readonly', 'type', 'mode', 'auth_mode', 'image_digest', 'mcp_gateway')


def inspect_shape(value, depth=0):
    """Shape only. Arbitrary names, scalar values and secret hashes are omitted."""
    if depth >= 4:
        return {'kind': 'depth_limit'}
    if type(value) is dict:
        return dict(kind='object', fields={key: inspect_shape(value[key], depth+1)
                    for key in INSPECT_FIELDS if key in value},
                    other_field_count=len(set(value)-set(INSPECT_FIELDS)))
    if type(value) is list:
        return dict(kind='list', count=len(value), samples=[inspect_shape(item, depth+1)
                    for item in value[:4]])
    return {'kind': 'scalar'}


def registration_metadata(value):
    """Manager schema field names only; never configuration/credential values."""
    if type(value) is not dict:
        raise ValueError('Registration object required')
    names = sorted(key for key in value if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', key))
    # Only a Docker-owned public image namespace may be emitted.
    image = value.get('image')
    public_image = (image if type(image) is str and re.fullmatch(
        r'(?:docker\.io/)?docker/sandbox-templates:[a-z0-9][a-z0-9._-]{0,100}', image) else None)
    return dict(field_names=names, excluded_field_names=len(value)-len(names),
                public_template_reference=public_image,
                agent_is_devin=value.get('agent') == 'devin',
                credential_configuration_verified=False)


def setting_observation(raw):
    # Unknown CLI representations are not guessed or echoed.
    if raw.strip() == 'false':
        return {'recognized': True, 'enabled': False}
    if raw.strip() == 'true':
        return {'recognized': True, 'enabled': True}
    return {'recognized': False}


def mcp_shape(raw):
    if len(raw.encode('utf-8')) > 1048576:
        raise ValueError('MCP inventory limit')
    value = json.loads(raw, object_pairs_hook=_pairs)
    if type(value) is list:
        return dict(root_type='list', entries=len(value), empty_inventory_verified=value == [])
    if type(value) is dict:
        observed = {}
        for key in ('servers', 'gateways'):
            if key in value:
                item = value[key]
                observed[key] = dict(kind='list' if type(item) is list else 'other',
                                     count=len(item) if type(item) is list else None)
        return dict(root_type='object', fields=observed,
                    gateway_state=(dict(local=value['gateway'].get('local')
                        if type(value['gateway'].get('local')) is bool else None,
                        decision_kind=type(value['gateway'].get('decision')).__name__,
                        decision_shape=inspect_shape(value['gateway'].get('decision')),
                        decision_known=value['gateway'].get('decision')
                        if value['gateway'].get('decision') in ('local','allow','deny','allowed','denied') else None)
                        if type(value.get('gateway')) is dict else None),
                    gateway_field_names=(sorted(key for key in value['gateway']
                        if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', key))
                        if type(value.get('gateway')) is dict else None),
                    metadata_fields_present=[key for key in MCP_METADATA_FIELDS if key in value],
                    unknown_fields=len(set(value)-{'servers', *MCP_METADATA_FIELDS}),
                    empty_inventory_verified=False)
    raise ValueError('Unexpected MCP inventory shape')


def main():
    require_managed_namespace()
    registration = json.loads(_file(ROOT/'sandbox-registry.json', 1048576), object_pairs_hook=_pairs)
    work = ROOT/tempfile.mkdtemp(prefix='host-integrations-', dir=ROOT)
    record = dict(schema=1, phase='checking', settings={}, all_vms_stopped=False,
                  settings_changed=False, model_executed=False, production_admitted=False)
    atomic_write_json(work/'receipt.json', record)
    try:
        with SandboxRuntime(registration, work) as runtime:
            inventory(registration)
            for key in SETTINGS:
                record['settings'][key] = setting_observation(run('settings', 'get', key, timeout=15))
            record['mcp'] = mcp_shape(run('mcp', 'ls', '--json', timeout=20))
            # Public interface only; never print sandbox inspect content.
            help_text = run('inspect', '--help', timeout=15)
            record['inspect_interface'] = dict(options=sorted(set(re.findall(
                r'--[a-z][a-z0-9-]{0,63}', help_text))))
            if '--json' in record['inspect_interface']['options']:
                from interactive_machine_auth import NAME, UUID
                entry = registration['roles']['machine']
                if entry.get('name') != NAME or entry.get('id') != UUID:
                    raise ValueError('Fixed machine registration required')
                raw = run('inspect', NAME, '--json', timeout=20)
                if len(raw.encode('utf-8')) > 1048576:
                    raise ValueError('Inspect size limit')
                value = json.loads(raw, object_pairs_hook=_pairs)
                record['machine_registration_shape'] = inspect_shape(value)
                record['machine_registration_metadata'] = registration_metadata(value)
                digest = value.get('image_digest')
                if type(digest) is str and re.fullmatch(r'sha256:[0-9a-f]{64}', digest):
                    record['observed_image_digest'] = digest
                mounts = value.get('runtime_mounts')
                record['runtime_mount_schema'] = (dict(count=len(mounts),
                    field_names=sorted({key for item in mounts if type(item) is dict
                        for key in item if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', key)}))
                    if type(mounts) is list else {'list_observed': False})
                from host_boundary_admission import check_host_boundary
                # Explicit reviewed observation, never adopt the current response
                # as the expected pin. Production registration remains unchanged.
                pin = 'sha256:df7d566115e4d16b23a0477be5677ea0eb569de027bc1933238859a6f62293fd'
                try:
                    check_host_boundary(runtime, 'machine', image_digest=pin, timeout=45)
                    record['host_contract_verified'] = True
                except (ValueError, RuntimeError, TimeoutError) as error:
                    record['host_contract_verified'] = False
                    record['host_contract_error_type'] = type(error).__name__
            inventory(registration)
            record.update(phase='complete', all_vms_stopped=True)
    finally:
        atomic_write_json(work/'receipt.json', record)
    print(json.dumps(dict(evidence=str(work), **record)), flush=True)


if __name__ == '__main__':
    import sys
    if sys.argv[1:]:
        raise ValueError('Fixed no-argument inspection required')
    main()
