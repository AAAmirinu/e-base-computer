"""Managed CLI refusal tests; no sbx process or VM is started."""
from contextlib import ExitStack
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import managed_cli_guard as guard
import sandbox_control


def service():
    return dict(ActiveState='active', SubState='running', User='fleet',
                PrivatePIDs='yes', Restart='no', KillMode='control-group',
                MainPID='900', InaccessiblePaths='/mnt/wslg /tmp/.X11-unix '
                '/run/WSL /run/user')


def metadata():
    return dict(pid_text='2', executable='/usr/bin/sbx',
                argv=b'/usr/bin/sbx\0daemon\0start\0',
                status='Name:\tsbx\nUid:\t1000\t1000\t1000\t1000\n',
                cgroup='0::/system.slice/e-base-sandboxd.service\n',
                own_ns={'mnt': 10, 'pid': 20}, daemon_ns={'mnt': 10, 'pid': 20})


class MetadataTests(unittest.TestCase):
    def test_valid_metadata(self):
        guard.validate_metadata(**metadata())
        value = metadata()
        value['pid_text'] = '1'  # Type=exec can be PID 1 inside PrivatePIDs.
        guard.validate_metadata(**value)

    def test_wrong_identity_rejected(self):
        for key, value in [('pid_text', '0'), ('pid_text', '２'),
                           ('pid_text', '2x'), ('executable', '/tmp/sbx'),
                           ('argv', b'/usr/bin/sbx\0daemon\0start\0--detach\0'),
                           ('status', 'Uid:\t1000\t0\t1000\t1000\n')]:
            with self.subTest(key=key, value=value):
                args = metadata()
                args[key] = value
                with self.assertRaises(RuntimeError):
                    guard.validate_metadata(**args)

    def test_cgroup_must_be_exact(self):
        for path in ['0::/init.scope', '0::/system.slice/e-base-sandboxd.service-evil',
                     '0::/system.slice/e-base-sandboxd.service/child',
                     '0::/system.slice/e-base-sandboxd.service\n1:cpu:/other']:
            with self.subTest(path=path):
                args = metadata()
                args['cgroup'] = path
                with self.assertRaises(RuntimeError):
                    guard.validate_metadata(**args)

    def test_each_namespace_must_match(self):
        for kind in ('mnt', 'pid'):
            with self.subTest(kind=kind):
                args = metadata()
                args['daemon_ns'][kind] += 1
                with self.assertRaises(RuntimeError):
                    guard.validate_metadata(**args)

    def test_missing_namespace_rejected(self):
        args = metadata()
        args['own_ns'] = args['daemon_ns'] = {'mnt': 10}
        with self.assertRaises(RuntimeError):
            guard.validate_metadata(**args)

    def test_effective_service_must_not_be_weakened(self):
        guard.validate_service(service())
        for key, value in [('ActiveState', 'inactive'), ('SubState', 'dead'),
                           ('User', 'root'), ('PrivatePIDs', 'no'),
                           ('Restart', 'always'), ('KillMode', 'process'),
                           ('InaccessiblePaths', '/mnt/wslg /tmp/.X11-unix /run/WSL')]:
            with self.subTest(key=key):
                values = service()
                values[key] = value
                with self.assertRaises(RuntimeError):
                    guard.validate_service(values)


class LiveCheckMockTests(unittest.TestCase):
    def run_check(self, *, changed_stat=False, changed_pid=False, changed_service=False):
        counts = {'stat': 0, 'pid': 0}

        class FakePath:
            def __init__(self, value):
                self.value = str(value)

            def __truediv__(self, part):
                return FakePath(self.value + '/' + str(part))

            def read_text(self):
                name = self.value.rsplit('/', 1)[-1]
                if name == 'pidfile':
                    counts['pid'] += 1
                    return '3' if changed_pid and counts['pid'] > 1 else '2'
                if name == 'stat':
                    counts['stat'] += 1
                    start = '101' if changed_stat and counts['stat'] > 1 else '100'
                    return '2 (sbx) ' + ' '.join(['0'] * 19 + [start])
                return metadata()[name]

            def read_bytes(self):
                return metadata()['argv']

        later = service()
        if changed_service:
            later['MainPID'] = '901'
        with ExitStack() as stack:
            stack.enter_context(patch.object(guard.sys, 'platform', 'linux'))
            stack.enter_context(patch.object(guard.os, 'getuid', return_value=1000, create=True))
            stack.enter_context(patch.dict(guard.os.environ, {'WSL_DISTRO_NAME': 'EBase-Sandboxes'}))
            stack.enter_context(patch.object(guard, 'PIDFILE', FakePath('pidfile')))
            stack.enter_context(patch.object(guard, 'Path', FakePath))
            stack.enter_context(patch.object(guard.os, 'stat', return_value=SimpleNamespace(st_ino=10)))
            stack.enter_context(patch.object(guard.os, 'readlink', return_value='/usr/bin/sbx'))
            stack.enter_context(patch.object(guard, 'service_info', side_effect=[service(), later]))
            guard.require_managed_namespace()

    def test_stable_generation_accepted(self):
        self.run_check()

    def test_generation_changes_rejected(self):
        for change in ('changed_stat', 'changed_pid', 'changed_service'):
            with self.subTest(change=change), self.assertRaisesRegex(RuntimeError, 'changed'):
                self.run_check(**{change: True})


class TransportRefusalTests(unittest.TestCase):
    def test_guard_refusal_never_spawns_client(self):
        for action in ('spawn', 'control'):
            with self.subTest(action=action), \
                    patch.object(sandbox_control.sys, 'platform', 'linux'), \
                    patch.object(sandbox_control, 'require_managed_namespace',
                                 side_effect=RuntimeError('outside namespace')) as check, \
                    patch.object(sandbox_control.subprocess, 'Popen') as popen:
                transport = sandbox_control.LinuxTransport()
                with self.assertRaisesRegex(RuntimeError, 'outside namespace'):
                    getattr(transport, action)(['/usr/bin/sbx', 'ls', '--json'],
                                               None if action == 'spawn' else 10)
                check.assert_called_once_with()
                popen.assert_not_called()


if __name__ == '__main__':
    unittest.main()
