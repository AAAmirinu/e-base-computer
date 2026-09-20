"""Synthetic in-container observations; never execute project code."""
import unittest
import validation_boundary_probe as probe


def fixture():
    status = {key: '0000000000000000' for key in ('CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb')}
    status.update(NoNewPrivs='1', Seccomp='2')
    return {'schema': 1, 'uid': 65532, 'euid': 65532, 'gid': 65532, 'egid': 65532,
            'groups': [], 'status': status, 'environment_keys': ['HOME', 'LANG', 'PATH'],
            'interfaces': ['lo'], 'ipv4_routes': [], 'ipv6_routes': [], 'unix_sockets': [],
            'sensitive_paths': {p: False for p in probe.SENSITIVE_PATHS},
            'mounts': [{'target': '/', 'options': ['ro'], 'fs': 'overlay'},
                       {'target': '/work', 'options': ['rw', 'nosuid', 'nodev'], 'fs': 'tmpfs'},
                       {'target': '/tmp', 'options': ['rw', 'nosuid', 'nodev', 'noexec'], 'fs': 'tmpfs'}]}


class BoundaryTests(unittest.TestCase):
    def test_success_is_not_full_acceptance(self):
        self.assertFalse(probe.verify(fixture())['full_isolation_accepted'])

    def test_missing_fields(self):
        for key in fixture():
            value = fixture()
            del value[key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                probe.verify(value)

    def test_identity_and_environment(self):
        for key, changed in [('uid', 0), ('euid', True), ('gid', 0), ('egid', 0),
                             ('groups', [0]), ('environment_keys', ['GH_TOKEN']),
                             ('interfaces', ['eth0', 'lo']), ('ipv4_routes', ['route']),
                             ('unix_sockets', ['socket'])]:
            value = fixture()
            value[key] = changed
            with self.subTest(key=key), self.assertRaises(ValueError):
                probe.verify(value)

    def test_capabilities_and_privileges(self):
        for key in fixture()['status']:
            value = fixture()
            value['status'][key] = 'bad'
            with self.subTest(key=key), self.assertRaises(ValueError):
                probe.verify(value)

    def test_ipv6_external_route_and_malformed(self):
        for route in ('bad', ' '.join(['0'] * 9 + ['eth0'])):
            value = fixture()
            value['ipv6_routes'] = [route]
            with self.assertRaises(ValueError):
                probe.verify(value)

    def test_sensitive_path_and_missing_observation(self):
        for key in probe.SENSITIVE_PATHS:
            value = fixture()
            value['sensitive_paths'][key] = True
            with self.subTest(key=key), self.assertRaises(ValueError):
                probe.verify(value)

    def test_mount_changes(self):
        for index, field, changed in [(0, 'options', ['rw']), (1, 'fs', 'virtiofs'),
                                      (1, 'options', ['rw']), (2, 'options', ['rw', 'nosuid', 'nodev'])]:
            value = fixture()
            value['mounts'][index][field] = changed
            with self.subTest(field=field, changed=changed), self.assertRaises(ValueError):
                probe.verify(value)

    def test_stacked_mount(self):
        value = fixture()
        value['mounts'].append(dict(value['mounts'][0]))
        with self.assertRaises(ValueError):
            probe.verify(value)

    def test_unexpected_mount_targets(self):
        for target in ('/leak', '/work/leak', '/proc/leak'):
            value = fixture()
            value['mounts'].append({'target': target, 'options': ['rw'], 'fs': 'ext4'})
            with self.subTest(target=target), self.assertRaises(ValueError):
                probe.verify(value)


if __name__ == '__main__':
    unittest.main()
