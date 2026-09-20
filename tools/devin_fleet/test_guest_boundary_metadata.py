"""Pure parser tests only; never invoke collect on the controller host."""
import unittest
from unittest.mock import patch, MagicMock
from types import SimpleNamespace
from guest_boundary_metadata import PATHS, VARIABLES, summarize, classify_mounts, docker_inodes, docker_owners

MOUNT = '1 0 0:1 / / rw - overlay overlay rw\n'
SOCKETS = 'Num RefCount Protocol Flags Type St Inode Path\n'


class MetadataTests(unittest.TestCase):
    def test_inaccessible_owner_is_not_a_clean_scan(self):
        entries = MagicMock()
        entries.__enter__.return_value = iter([SimpleNamespace(name='10', path='/proc/10')])
        with patch('guest_boundary_metadata.os.scandir', side_effect=[entries, PermissionError()]):
            value = docker_owners(SOCKETS+'000: 2 0 0 1 1 42 /run/docker.sock\n')
        self.assertFalse(value['scan_complete'])
        self.assertFalse(value['host_boundary_proven'])
        self.assertEqual(value['inaccessible_processes'], 1)

    def test_owner_match_never_attests_boundary(self):
        entries, descriptors = MagicMock(), MagicMock()
        entries.__enter__.return_value = iter([SimpleNamespace(name='10', path='/proc/10')])
        descriptors.__enter__.return_value = iter([SimpleNamespace(path='/proc/10/fd/3')])
        with patch('guest_boundary_metadata.os.scandir', side_effect=[entries, descriptors]), \
             patch('guest_boundary_metadata.os.readlink', return_value='socket:[42]'), \
             patch('guest_boundary_metadata.bounded_read', return_value='dockerd\n') as read:
            value = docker_owners(SOCKETS+'000: 2 0 0 1 1 42 /run/docker.sock\n')
        read.assert_called_once_with('/proc/10/comm', 64)
        self.assertEqual(value['dockerd_owners'], 1)
        self.assertFalse(value['host_boundary_proven'])

    def test_docker_inode_selection(self):
        value = docker_inodes(SOCKETS+'000: 2 0 0 1 1 42 /var/run/docker.sock\n'
                              +'000: 2 0 0 1 1 43 /private/other.sock\n')
        self.assertEqual(value, {'42'})

    def test_bad_docker_inode_rejected(self):
        with self.assertRaises(ValueError):
            docker_inodes(SOCKETS+'000: 2 0 0 1 1 bad /run/docker.sock\n')

    def test_fixed_shared_mount_classification(self):
        value = classify_mounts('1 0 0:1 / /etc/hosts ro - virtiofs secret rw\n')
        self.assertEqual(value, [dict(filesystem='virtiofs', target='/etc/hosts',
                                     mount_readonly=True, filesystem_readonly=False)])
        self.assertNotIn('secret', str(value))

    def test_unknown_mount_target_suppressed(self):
        value = classify_mounts('1 0 0:1 / /private/user rw - virtiofs private rw\n')
        self.assertEqual(value[0]['target'], 'unclassified')
        self.assertNotIn('private', str(value))

    def result(self, **updates):
        args = dict(mountinfo=MOUNT, unix_sockets=SOCKETS, meminfo='MemTotal: 4000000 kB\n',
                    uid=1000, cpu_count=2, paths=dict.fromkeys(PATHS, False),
                    variables=dict.fromkeys(VARIABLES, False))
        args.update(updates)
        return summarize(**args)

    def test_no_attestation(self):
        value = self.result()
        self.assertFalse(value['full_boundary_accepted'])
        self.assertFalse(value['network_attempted'])
        self.assertEqual(value['logical_cpu_count'], 2)

    def test_shared_mount_no_path_disclosure(self):
        result = self.result(mountinfo=MOUNT+'2 1 0:2 / /secret rw - virtiofs secret rw\n')
        self.assertEqual(result['shared_filesystem_counts']['virtiofs'], 1)
        self.assertNotIn('secret', str(result))

    def test_socket_names_not_exported(self):
        result = self.result(unix_sockets=SOCKETS+'000: 2 0 0 1 1 42 @/tmp/.X11-unix/X99\n')
        self.assertEqual(result['abstract_display_socket_count'], 1)
        self.assertNotIn('X99', str(result))

    def test_missing_or_malformed_proc_fails(self):
        for values in ({'mountinfo': ''}, {'mountinfo': 'bad'}, {'unix_sockets': ''},
                       {'unix_sockets': SOCKETS+'bad'}, {'meminfo': ''},
                       {'meminfo': 'MemTotal: 1 kB\nMemTotal: 2 kB\n'}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.result(**values)

    def test_observations_are_not_configuration_claims(self):
        self.assertEqual(self.result(cpu_count=16)['logical_cpu_count'], 16)
        self.assertFalse(self.result(cpu_count=16)['full_boundary_accepted'])

    def test_typed_presence_and_identity(self):
        for values in ({'uid': True}, {'cpu_count': None}, {'paths': {}},
                       {'variables': dict.fromkeys(VARIABLES, 'secret')}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.result(**values)


if __name__ == '__main__':
    unittest.main()
