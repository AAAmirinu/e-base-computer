import unittest
import json
from managed_sandbox_status import validate_service, service_info, status_command, parse_status, ROLES


class ManagedStatusTests(unittest.TestCase):
    def setUp(self):
        self.values = {'ActiveState': 'active', 'SubState': 'running', 'User': 'fleet',
            'Restart': 'no', 'KillMode': 'control-group',
            'PrivatePIDs': 'yes', 'MainPID': '123',
            'InaccessiblePaths': '/mnt/wslg /tmp/.X11-unix /run/WSL /run/user'}

    def test_complete_service_identity(self):
        self.assertEqual(validate_service(self.values), 123)

    def test_stopped_or_weakened_service(self):
        for key, value in [('ActiveState', 'inactive'), ('SubState', 'dead'), ('User', 'root'),
                           ('PrivatePIDs', 'no'), ('InaccessiblePaths', '/mnt/wslg'),
                           ('Restart', 'always'), ('KillMode', 'process'),
                           ('MainPID', '0'), ('MainPID', 'abc')]:
            old = self.values[key]
            self.values[key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                validate_service(self.values)
            self.values[key] = old

    def test_unknown_unit_never_spawns(self):
        with self.assertRaises(ValueError):
            service_info('unrelated.service')

    def test_fixed_controller_action_drops_into_status_only(self):
        args = status_command(True)
        self.assertEqual(args[:3], ['/usr/bin/python3', '-E', '-s'])
        self.assertEqual(args[-1], 'status')
        self.assertIn('/home/fleet/controller-validation/managed-maintenance', args)
        self.assertNotIn('--resume', args)

    def test_no_arbitrary_command_argument(self):
        for argument in ('exec', ['sh'], None, 1):
            with self.subTest(argument=argument), self.assertRaises(ValueError):
                status_command(argument)

    def test_strict_controller_result(self):
        value = {'roles': {role: 'stopped' for role in ROLES}, 'stop_requested': True,
                 'mode': 'maintenance_only', 'resume_available': False}
        self.assertEqual(parse_status(json.dumps(value), True), value)
        value['resume_available'] = 0
        with self.assertRaises(RuntimeError):
            parse_status(json.dumps(value), True)
        with self.assertRaises(ValueError):
            parse_status('{"roles":{},"roles":{}}', True)


if __name__ == '__main__':
    unittest.main()
