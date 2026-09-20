"""Synthetic Docker metadata contract tests; Docker is never invoked."""
import copy
import unittest

import sandbox_validation_container as spec

IMAGE = 'sha256:' + 'a' * 64
OP = 'b' * 32


def fixture():
    return {'Id': 'c' * 64, 'Image': IMAGE, 'Name': '/e-base-check-' + OP,
            'State': {'Status': 'created', 'Running': False}, 'Mounts': [],
            'NetworkSettings': {'Networks': {'none': {}}},
            'Config': {'User': '65532:65532', 'WorkingDir': '/work',
                       'Entrypoint': ['/usr/bin/env'], 'Cmd': list(spec.COMMAND),
                       'Labels': {spec.LABEL: OP}, 'Healthcheck': {'Test': ['NONE']},
                       'Env': ['PATH=/usr/local/bin:/usr/bin:/bin', 'LANG=C.UTF-8']},
            'HostConfig': {'NetworkMode': 'none', 'Privileged': False, 'ReadonlyRootfs': True,
                           'CapDrop': ['ALL'], 'SecurityOpt': ['no-new-privileges=true'],
                           'Memory': 536870912, 'MemorySwap': 536870912, 'NanoCpus': 1000000000,
                           'PidsLimit': 64, 'Tmpfs': dict(spec.TMPFS), 'Runtime': 'runc',
                           'PidMode': 'private', 'IpcMode': 'private', 'UTSMode': '', 'UsernsMode': '',
                           'RestartPolicy': {'Name': 'no', 'MaximumRetryCount': 0},
                           'LogConfig': {'Type': 'local', 'Config': {'max-size': '1m', 'max-file': '1', 'compress': 'false'}},
                           'Ulimits': [{'Name': 'nofile', 'Hard': 256, 'Soft': 256}]}}


class ValidationContainerTests(unittest.TestCase):
    def test_fixed_arguments(self):
        argv = spec.create_arguments(IMAGE, OP)
        self.assertEqual(argv[:2], ['docker', 'create'])
        self.assertEqual(argv[argv.index('--pull') + 1], 'never')
        self.assertEqual(argv[argv.index('--network') + 1], 'none')
        self.assertEqual(argv[argv.index(IMAGE) + 1:], spec.COMMAND)
        self.assertNotIn('--privileged', argv)
        self.assertNotIn('--volume', argv)
        self.assertNotIn('--rm', argv)

    def test_tags_and_bad_operations_refused(self):
        for image, op in [('python:3.12-slim', OP), (IMAGE, '../x'), (IMAGE.upper(), OP), (IMAGE, True)]:
            with self.subTest(image=image, op=op), self.assertRaises(ValueError):
                spec.create_arguments(image, op)

    def test_image_environment_and_volumes(self):
        image = {'Id': IMAGE, 'Os': 'linux', 'Architecture': 'amd64', 'Config': {'Env': []}}
        self.assertEqual(spec.admit_image(image), IMAGE)
        for config in ({'Env': ['GH_TOKEN=secret']}, {'Env': ['LD_PRELOAD=x']},
                       {'Env': ['PATH=x', 'PATH=y']}, {'Env': [], 'Volumes': {'/x': {}}},
                       {'Env': [], 'OnBuild': ['RUN x']}, {'Env': [], 'ExposedPorts': {'80/tcp': {}}}):
            with self.subTest(config=config), self.assertRaises(ValueError):
                spec.admit_image(dict(image, Config=config))

    def test_valid_inspect(self):
        self.assertEqual(spec.verify_created_container(fixture(), IMAGE, OP), 'c' * 64)

    def test_missing_enforced_fields(self):
        for key in fixture()['HostConfig']:
            value = fixture()
            del value['HostConfig'][key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                spec.verify_created_container(value, IMAGE, OP)

    def test_isolation_changes(self):
        changes = {'NetworkMode': 'host', 'Privileged': True, 'ReadonlyRootfs': False,
                   'CapDrop': [], 'SecurityOpt': [], 'Memory': 0, 'MemorySwap': -1,
                   'NanoCpus': 0, 'PidsLimit': 0, 'Tmpfs': {}, 'Runtime': 'custom',
                   'PidMode': 'host', 'IpcMode': 'host', 'UTSMode': 'host', 'UsernsMode': 'host',
                   'RestartPolicy': {'Name': 'always'}, 'LogConfig': {}, 'Ulimits': []}
        for key, changed in changes.items():
            value = fixture()
            value['HostConfig'][key] = changed
            with self.subTest(key=key), self.assertRaises(ValueError):
                spec.verify_created_container(value, IMAGE, OP)

    def test_extra_resources(self):
        for key in ('Binds', 'Mounts', 'VolumesFrom', 'Devices', 'DeviceRequests', 'CapAdd',
                    'GroupAdd', 'PortBindings', 'ExtraHosts', 'Links', 'Dns', 'DnsSearch', 'DeviceCgroupRules'):
            value = fixture()
            value['HostConfig'][key] = ['unexpected']
            with self.subTest(key=key), self.assertRaises(ValueError):
                spec.verify_created_container(value, IMAGE, OP)

    def test_identity_and_mount_mismatch(self):
        for key, changed in [('Id', 'bad'), ('Image', 'sha256:' + 'd' * 64), ('Name', '/other'),
                             ('Mounts', [{'Type': 'bind'}]), ('State', {'Status': 'running', 'Running': True})]:
            value = fixture()
            value[key] = changed
            with self.subTest(key=key), self.assertRaises(ValueError):
                spec.verify_created_container(value, IMAGE, OP)

    def test_command_mismatch(self):
        for key, changed in [('User', '0'), ('WorkingDir', '/'), ('Entrypoint', ['/bin/sh']),
                             ('Cmd', ['bad']), ('Labels', {}), ('Healthcheck', {}), ('Env', ['SSH_AUTH_SOCK=x'])]:
            value = copy.deepcopy(fixture())
            value['Config'][key] = changed
            with self.subTest(key=key), self.assertRaises(ValueError):
                spec.verify_created_container(value, IMAGE, OP)

    def test_extra_network_attachment(self):
        for networks in ({}, {'bridge': {}}, {'none': {}, 'bridge': {}}):
            value = fixture()
            value['NetworkSettings']['Networks'] = networks
            with self.assertRaises(ValueError):
                spec.verify_created_container(value, IMAGE, OP)


if __name__ == '__main__':
    unittest.main()
