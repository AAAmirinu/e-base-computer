"""Narrow observed guest-sharing contract, not full isolation acceptance.

Credential values, Docker daemon provenance and resource limits are not proven.
The manager-side checks and exact guest tool policy remain separate gates.
"""
from guest_boundary_receipt import validate_metadata


def validate_guest_contract(metadata):
    value = validate_metadata(metadata)
    if value['uid'] != 1000:
        raise ValueError('Expected guest user required')
    for path, present in value['fixed_paths_present'].items():
        if present is not (path == '/var/run/docker.sock'):
            raise ValueError('Unexpected guest path presence')
    if value['docker_socket_metadata'] != dict(present=True, kind='socket', uid=0,
                                              gid=1001, mode=0o660):
        raise ValueError('Unexpected Docker socket metadata')
    if value['ssh_socket_metadata'] != dict(present=False, errno=2):
        raise ValueError('SSH socket absence not established')
    if value['abstract_display_socket_count'] != 0:
        raise ValueError('Display socket prohibited')
    for key in ('DISPLAY', 'WSL_INTEROP', 'DBUS_SESSION_BUS_ADDRESS'):
        if value['variable_names_present'][key]:
            raise ValueError('Host integration variable prohibited')
    details = value['shared_mount_details']
    if (len(details) != 2
            or {item['target'] for item in details} != {'/etc/hosts', '/etc/resolv.conf'}
            or any(item['filesystem'] != 'virtiofs' or item['mount_readonly'] is not True
                   for item in details)):
        raise ValueError('Only fixed read-only host configuration mounts permitted')
    # validate_metadata already binds per-filesystem counts to these exact rows.
    # Filesystem-level rw does not override the required per-mount ro property.
    # Owner observations remain diagnostic, even if the scan is incomplete.
