"""Pure synthetic contract tests; never call the guest collector."""
import copy
import unittest

from guest_boundary_contract import validate_guest_contract
from test_guest_boundary_receipt import fixture as metadata_fixture


def fixture():
    value = metadata_fixture()
    value['fixed_paths_present']['/var/run/docker.sock'] = True
    for key in ('GH_TOKEN', 'WAYLAND_DISPLAY', 'SSH_AUTH_SOCK'):
        value['variable_names_present'][key] = True
    value['docker_socket_owners'].update(dockerd_owners=0, inaccessible_processes=2,
                                        scan_complete=False)
    return value


class GuestBoundaryContractTests(unittest.TestCase):
    def rejected(self, change):
        value = fixture()
        change(value)
        with self.assertRaises(ValueError):
            validate_guest_contract(value)

    def test_matching_metadata_returns_none_without_mutation(self):
        value = fixture()
        original = copy.deepcopy(value)
        self.assertIsNone(validate_guest_contract(value))
        self.assertEqual(value, original)

    def test_schema_validation_precedes_contract(self):
        self.rejected(lambda v: v.update(secret='private'))
        self.rejected(lambda v: v.update(uid=True))
        self.rejected(lambda v: v.update(full_boundary_accepted=True))
        self.rejected(lambda v: v['docker_socket_metadata'].update(uid=False))
        self.rejected(lambda v: v['fixed_paths_present'].update({'/host': 0}))

    def test_uid_and_all_fixed_paths(self):
        self.rejected(lambda v: v.update(uid=0))
        for path in fixture()['fixed_paths_present']:
            with self.subTest(path=path):
                self.rejected(lambda v: v['fixed_paths_present'].update(
                    {path: not v['fixed_paths_present'][path]}))

    def test_exact_docker_socket_metadata(self):
        for field, invalid in (('kind', 'symlink'), ('kind', 'directory'), ('uid', 1000),
                               ('gid', 0), ('mode', 0o666), ('mode', 0o600)):
            self.rejected(lambda v: v['docker_socket_metadata'].update({field: invalid}))
        self.rejected(lambda v: v.update(docker_socket_metadata=dict(present=False, errno=2)))

    def test_ssh_absence_requires_enoent_not_unknown_scope(self):
        for invalid in (dict(present=False, errno=13), dict(path_not_in_probe_scope=True),
                        dict(present=True, kind='socket', uid=1000, gid=1000, mode=0o600)):
            self.rejected(lambda v: v.update(ssh_socket_metadata=invalid))

    def test_display_and_dangerous_environment(self):
        self.rejected(lambda v: v.update(abstract_display_socket_count=1))
        for key in ('DISPLAY', 'WSL_INTEROP', 'DBUS_SESSION_BUS_ADDRESS'):
            self.rejected(lambda v: v['variable_names_present'].update({key: True}))

    def test_other_environment_keys_do_not_claim_credential_absence(self):
        for key in fixture()['variable_names_present']:
            if key not in ('DISPLAY', 'WSL_INTEROP', 'DBUS_SESSION_BUS_ADDRESS'):
                for present in (True, False):
                    value = fixture()
                    value['variable_names_present'][key] = present
                    self.assertIsNone(validate_guest_contract(value))

    def test_mount_order_and_filesystem_ro_are_not_extra_requirements(self):
        value = fixture()
        value['shared_mount_details'].reverse()
        value['shared_mount_details'][0]['filesystem_readonly'] = True
        self.assertIsNone(validate_guest_contract(value))

    def test_mount_contract_rejects_consistent_but_different_inventory(self):
        self.rejected(lambda v: v['shared_mount_details'][0].update(mount_readonly=False))
        self.rejected(lambda v: v['shared_mount_details'][0].update(target='/etc/resolv.conf'))
        self.rejected(lambda v: v['shared_mount_details'][0].update(target='unclassified'))
        def alternate_fs(v):
            v['shared_mount_details'][0]['filesystem'] = '9p'
            v['shared_filesystem_counts'].update(virtiofs=1, **{'9p': 1})
        self.rejected(alternate_fs)
        def added(v):
            v['shared_mount_details'].append(dict(filesystem='cifs', target='/workspace',
                mount_readonly=True, filesystem_readonly=True))
            v['shared_filesystem_counts']['cifs'] = 1
        self.rejected(added)
        def missing(v):
            v['shared_mount_details'].pop()
            v['shared_filesystem_counts']['virtiofs'] = 1
        self.rejected(missing)

    def test_resources_and_incomplete_owner_scan_are_observations(self):
        value = fixture()
        value.update(logical_cpu_count=16, mem_total_kib=65536000, mount_count=24)
        self.assertIsNone(validate_guest_contract(value))
        self.assertIs(value['docker_socket_owners']['host_boundary_proven'], False)
        self.assertIs(value['full_boundary_accepted'], False)


if __name__ == '__main__':
    unittest.main()
