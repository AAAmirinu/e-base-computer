"""Strict, data-only validation of maintenance metadata; never an attestation."""
from copy import deepcopy

from guest_boundary_metadata import MOUNT_TARGETS, PATHS, SHARED_FS, VARIABLES


def _keys(value, expected):
    if type(value) is not dict or set(value) != set(expected):
        raise ValueError('Unexpected metadata fields')


def _integer(value, lower=0, upper=2**32 - 1):
    if type(value) is not int or not lower <= value <= upper:
        raise ValueError('Invalid metadata integer')


def _presence(value, names):
    _keys(value, names)
    if any(type(item) is not bool for item in value.values()):
        raise ValueError('Invalid presence observation')


def _socket(value, *, ssh=False):
    if type(value) is not dict:
        raise ValueError('Invalid socket observation')
    if ssh and set(value) == {'path_not_in_probe_scope'}:
        if value['path_not_in_probe_scope'] is not True:
            raise ValueError('Invalid scope observation')
        return
    if value.get('present') is False:
        _keys(value, ('present', 'errno'))
        _integer(value['errno'], 1, 4095)
    elif value.get('present') is True:
        _keys(value, ('present', 'kind', 'uid', 'gid', 'mode'))
        if type(value['kind']) is not str or value['kind'] not in ('socket', 'symlink', 'directory', 'other'):
            raise ValueError('Invalid socket type')
        _integer(value['uid'])
        _integer(value['gid'])
        _integer(value['mode'], 0, 0o7777)
    else:
        raise ValueError('Invalid socket presence')


def validate_metadata(metadata):
    """Return a detached validated observation, not permission to run a model."""
    _keys(metadata, ('schema', 'uid', 'logical_cpu_count', 'mem_total_kib',
        'mount_count', 'shared_filesystem_counts', 'abstract_display_socket_count',
        'fixed_paths_present', 'variable_names_present', 'network_attempted',
        'credentials_read', 'model_executed', 'full_boundary_accepted',
        'shared_mount_details', 'docker_socket_metadata', 'ssh_socket_metadata',
        'docker_socket_owners'))
    _integer(metadata['schema'], 1, 1)
    _integer(metadata['uid'])
    _integer(metadata['logical_cpu_count'], 1, 1048576)
    _integer(metadata['mem_total_kib'], 1, 2**53 - 1)
    _integer(metadata['mount_count'], 1, 1048576)
    _integer(metadata['abstract_display_socket_count'], 0, 1048576)
    for name in ('network_attempted', 'credentials_read', 'model_executed', 'full_boundary_accepted'):
        if metadata[name] is not False:
            raise ValueError('Unsafe or ambiguous metadata flag')
    _presence(metadata['fixed_paths_present'], PATHS)
    _presence(metadata['variable_names_present'], VARIABLES)
    counts = metadata['shared_filesystem_counts']
    _keys(counts, SHARED_FS)
    for count in counts.values():
        _integer(count, 0, metadata['mount_count'])
    details = metadata['shared_mount_details']
    if type(details) is not list or len(details) > metadata['mount_count']:
        raise ValueError('Invalid shared mount inventory')
    observed = dict.fromkeys(SHARED_FS, 0)
    for item in details:
        _keys(item, ('filesystem', 'target', 'mount_readonly', 'filesystem_readonly'))
        fs, target = item['filesystem'], item['target']
        if type(fs) is not str or fs not in SHARED_FS:
            raise ValueError('Unknown shared filesystem')
        if type(target) is not str or target not in (*MOUNT_TARGETS, 'unclassified'):
            raise ValueError('Unknown mount target')
        if type(item['mount_readonly']) is not bool or type(item['filesystem_readonly']) is not bool:
            raise ValueError('Invalid mount flag')
        observed[fs] += 1
    if observed != counts:
        raise ValueError('Inconsistent shared mount counts')
    _socket(metadata['docker_socket_metadata'])
    _socket(metadata['ssh_socket_metadata'], ssh=True)
    owners = metadata['docker_socket_owners']
    _keys(owners, ('endpoint_inodes', 'dockerd_owners', 'other_owners',
                  'inaccessible_processes', 'scan_complete', 'host_boundary_proven'))
    _integer(owners['endpoint_inodes'], 0, 65536)
    for key in ('dockerd_owners', 'other_owners', 'inaccessible_processes'):
        _integer(owners[key], 0, 1024)
    if owners['dockerd_owners'] + owners['other_owners'] > 1024:
        raise ValueError('Invalid socket owner count')
    if type(owners['scan_complete']) is not bool or owners['host_boundary_proven'] is not False:
        raise ValueError('Invalid socket ownership flags')
    return deepcopy(metadata)
