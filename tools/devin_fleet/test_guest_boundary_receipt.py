"""Synthetic observations only: no collect, VM, subprocess or network."""
import copy
import unittest

from guest_boundary_metadata import PATHS, SHARED_FS, VARIABLES
from guest_boundary_receipt import validate_metadata


def fixture():
    return dict(schema=1, uid=1000, logical_cpu_count=4, mem_total_kib=4096000,
        mount_count=12, abstract_display_socket_count=0,
        shared_filesystem_counts={name: (2 if name == 'virtiofs' else 0) for name in SHARED_FS},
        fixed_paths_present=dict.fromkeys(PATHS, False),
        variable_names_present=dict.fromkeys(VARIABLES, False),
        network_attempted=False, credentials_read=False, model_executed=False,
        full_boundary_accepted=False,
        shared_mount_details=[dict(filesystem='virtiofs', target=target,
            mount_readonly=True, filesystem_readonly=False)
            for target in ('/etc/hosts', '/etc/resolv.conf')],
        docker_socket_metadata=dict(present=True, kind='socket', uid=0, gid=1001, mode=0o660),
        ssh_socket_metadata=dict(present=False, errno=2),
        docker_socket_owners=dict(endpoint_inodes=1, dockerd_owners=1,
            other_owners=0, inaccessible_processes=0, scan_complete=True,
            host_boundary_proven=False))


class GuestBoundaryReceiptTests(unittest.TestCase):
    def rejected(self, mutate):
        value = fixture()
        mutate(value)
        with self.assertRaises(ValueError):
            validate_metadata(value)

    def test_valid_detached_observation(self):
        value = fixture()
        checked = validate_metadata(value)
        self.assertEqual(checked, value)
        checked['shared_mount_details'].clear()
        self.assertEqual(len(value['shared_mount_details']), 2)

    def test_top_fields_exact(self):
        for field in fixture():
            with self.subTest(field=field):
                self.rejected(lambda v: v.pop(field))
        self.rejected(lambda v: v.update(secret='not-to-return'))
        for value in (None, [], 'secret', True):
            with self.assertRaises(ValueError):
                validate_metadata(value)

    def test_integer_types_and_ranges(self):
        for key in ('schema', 'uid', 'logical_cpu_count', 'mem_total_kib', 'mount_count', 'abstract_display_socket_count'):
            for invalid in (True, False, 1.0, '1', None, -1, 2**64):
                with self.subTest(key=key, invalid=invalid):
                    self.rejected(lambda v: v.update({key: invalid}))
        for key in ('schema', 'logical_cpu_count', 'mem_total_kib', 'mount_count'):
            self.rejected(lambda v: v.update({key: 0}))

    def test_false_safety_flags_exact(self):
        for key in ('network_attempted', 'credentials_read', 'model_executed', 'full_boundary_accepted'):
            for invalid in (True, 0, None, 'false'):
                self.rejected(lambda v: v.update({key: invalid}))

    def test_fixed_presence_maps(self):
        for key in ('fixed_paths_present', 'variable_names_present'):
            self.rejected(lambda v: v[key].update(secret=False))
            self.rejected(lambda v: v[key].pop(next(iter(v[key]))))
            self.rejected(lambda v: v[key].update({next(iter(v[key])): 1}))
            self.rejected(lambda v: v.update({key: []}))

    def test_mount_counts_and_detail_schema(self):
        for invalid in (True, -1, 13, 1.0):
            self.rejected(lambda v: v['shared_filesystem_counts'].update(virtiofs=invalid))
        self.rejected(lambda v: v['shared_filesystem_counts'].update(virtiofs=1))
        self.rejected(lambda v: v['shared_filesystem_counts'].update(secret=0))
        self.rejected(lambda v: v['shared_mount_details'].append(copy.deepcopy(v['shared_mount_details'][0])))
        for key, invalid in (('filesystem', []), ('filesystem', 'secret'), ('target', '/private/path'),
                             ('target', None), ('mount_readonly', 1), ('filesystem_readonly', 'true'), ('secret', 'value')):
            self.rejected(lambda v: v['shared_mount_details'][0].update({key: invalid}))
        self.rejected(lambda v: v.update(shared_mount_details={}))

    def test_socket_branches(self):
        for key in ('docker_socket_metadata', 'ssh_socket_metadata'):
            for valid in (dict(present=False, errno=2), dict(present=True, kind='symlink', uid=0, gid=0, mode=0o777)):
                value = fixture()
                value[key] = valid
                self.assertEqual(validate_metadata(value), value)
            for invalid in ({}, [], dict(present=0, errno=2), dict(present=False, errno=True),
                            dict(present=False, errno=0), dict(present=False, errno=2, path='/secret'),
                            dict(present=True, kind='socket', uid=True, gid=0, mode=0o660),
                            dict(present=True, kind='socket', uid=0, gid=0, mode=0o10000),
                            dict(present=True, kind='unknown', uid=0, gid=0, mode=0)):
                self.rejected(lambda v: v.update({key: invalid}))
        value = fixture()
        value['ssh_socket_metadata'] = dict(path_not_in_probe_scope=True)
        self.assertEqual(validate_metadata(value), value)
        self.rejected(lambda v: v.update(docker_socket_metadata=dict(path_not_in_probe_scope=True)))
        self.rejected(lambda v: v.update(ssh_socket_metadata=dict(path_not_in_probe_scope=1)))

    def test_error_does_not_include_raw_secret(self):
        value = fixture()
        value['secret'] = 'PRIVATE_VALUE_DO_NOT_ECHO'
        try:
            validate_metadata(value)
        except ValueError as error:
            self.assertNotIn('PRIVATE_VALUE_DO_NOT_ECHO', str(error))
        else:
            self.fail('Unexpected acceptance')

    def test_socket_owner_schema_and_bounds(self):
        for key in fixture()['docker_socket_owners']:
            self.rejected(lambda v: v['docker_socket_owners'].pop(key))
        self.rejected(lambda v: v['docker_socket_owners'].update(secret='private'))
        for key, maximum in (('endpoint_inodes', 65536), ('dockerd_owners', 1024),
                             ('other_owners', 1024), ('inaccessible_processes', 1024)):
            for invalid in (True, 1.0, -1, maximum + 1, None):
                self.rejected(lambda v: v['docker_socket_owners'].update({key: invalid}))
        self.rejected(lambda v: v['docker_socket_owners'].update(dockerd_owners=1024, other_owners=1))
        self.rejected(lambda v: v['docker_socket_owners'].update(scan_complete=1))
        for invalid in (0, True, None):
            self.rejected(lambda v: v['docker_socket_owners'].update(host_boundary_proven=invalid))
        value = fixture()
        value['docker_socket_owners'].update(scan_complete=False, inaccessible_processes=1024)
        self.assertEqual(validate_metadata(value), value)


if __name__ == '__main__':
    unittest.main()
