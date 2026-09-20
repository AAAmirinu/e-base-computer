"""Kill owned synthetic workers only; VM/CLI/network transports are forbidden."""
from contextlib import ExitStack
import json
import os
import signal
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

import model_network_window as window
import model_network_admission as network
import recover_model_network as recovery
import sandbox_control
import sandbox_runtime
from durable import atomic_write_json
from network_restart_guard import inspect_windows
from process_control import GlobalLock, global_lock_held
from sandbox_repository import GuestRepository


class FakeTransport:
    def __init__(self, base, case=None):
        self.base, self.case = Path(base), case

    def control(self, argv, timeout):
        state = json.loads((self.base / 'policy.json').read_bytes())
        if argv == ['/usr/bin/sbx', 'ls', '--json']:
            return SimpleNamespace(returncode=0, stdout=json.dumps({'sandboxes': state['inventory']}))
        if argv[:2] != ['/usr/bin/sbx', 'policy']:
            raise AssertionError('VM and CLI operations forbidden')
        action = argv[2]
        code = 0
        if action == 'ls':
            result = {'rules': state['rules']}
        elif action == 'check':
            allow, deny = set(), set()
            for row in state['rules']:
                (allow if row['decision'] == 'allow' else deny).update(row['resources'])
            allowed = '**' not in deny and argv[-1] in allow - deny
            result, code = {'allowed': allowed}, 0 if allowed else 1
        elif action == 'deny':
            if argv[3:6] != ['network', '--sandbox', 'e-base-machine']:
                raise AssertionError('Unexpected policy target')
            state['serial'] += 1
            row = dict(state['rules'][0], id='owned-' + str(state['serial']), editable=True,
                       decision='deny', resources=argv[-1].split(','))
            state['rules'].append(row)
            atomic_write_json(self.base / 'policy.json', state)
            result = {}
        elif action == 'rm':
            if argv != ['/usr/bin/sbx', 'policy', 'rm', 'network', '--sandbox',
                        'e-base-machine', '--id', 'original']:
                raise AssertionError('Only original fake denial may be removed')
            state['rules'] = [row for row in state['rules'] if row['id'] != 'original']
            atomic_write_json(self.base / 'policy.json', state)
            if self.case == 'opening':
                mark_and_wait(self.base)
            result = {}
        else:
            raise AssertionError('Unknown transport action')
        return SimpleNamespace(returncode=code, stdout=json.dumps(result))


def mark_and_wait(base):
    atomic_write_json(base / 'ready.json', {'ready': True})
    # Only the test's owned child blocks here; parent kills and reaps it.
    while True:
        time.sleep(0.1)


def isolation_patches(base):
    stack = ExitStack()
    for module in (window, network, recovery):
        stack.enter_context(patch.object(module, 'require_managed_namespace', return_value=None))
    for module in (recovery, sandbox_runtime, sandbox_control):
        stack.enter_context(patch.object(module, 'LinuxTransport',
            side_effect=AssertionError('Real LinuxTransport forbidden')))
    lock = Path(base) / 'test-global.lock'
    stack.enter_context(patch.object(window, 'global_lock_held', side_effect=lambda path: global_lock_held(lock)))
    stack.enter_context(patch.object(recovery, 'GlobalLock', side_effect=lambda path: GlobalLock(lock)))
    stack.enter_context(patch.object(recovery, 'ROOT', Path(base)))
    return stack


def worker(base, case):
    base = Path(base)
    registration = json.loads((base / 'sandbox-registry.json').read_bytes())
    root = Path(registration['controller_root'])
    controller = SimpleNamespace(fenced=False, sandbox_id=registration['roles']['machine']['id'],
                                 stop=lambda: None)
    with isolation_patches(base), GlobalLock(base / 'test-global.lock'):
        runtime = sandbox_runtime.SandboxRuntime(registration, root, transport=FakeTransport(base, case))
        runtime._entered = True
        runtime._active['machine'] = (controller, controller)
        repo = GuestRepository(controller, '/home/agent/workspace/machine', root / 'logs',
                               external_stop=runtime.stop_path)
        with window.model_network_window(runtime, 'machine', repo, root / 'turn/network-window', timeout=8):
            mark_and_wait(base)


@unittest.skipUnless(sys.platform == 'linux', 'Owned SIGKILL worker requires Linux')
class NetworkProcessCrashTests(unittest.TestCase):
    def run_case(self, case):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            root = base / 'controller'
            root.mkdir(mode=0o700)
            run = root / 'turn'
            run.mkdir(mode=0o700)
            fences = root / 'model-turn-fences'
            fences.mkdir(mode=0o700)
            registration = dict(schema=1, production_enabled=True, controller_root=str(root),
                simultaneous_capacity_verified=1, migration_epoch='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
                roles={role: dict(name='e-base-' + role, id=str(uuid.UUID(int=i + 1)))
                       for i, role in enumerate(sorted(sandbox_runtime.ROLES))})
            atomic_write_json(base / 'sandbox-registry.json', registration)
            fence_path = fences / 'machine.json'
            atomic_write_json(fence_path, dict(schema=1, role='machine', sequence=0, operation_id='b' * 32,
                migration_epoch=registration['migration_epoch'], sandbox_id=registration['roles']['machine']['id'],
                run_directory=str(run), state='unresolved', automatic_resume=False))
            common = dict(resource_type='network', scope='sandbox:e-base-machine',
                          applies_to='sandbox:e-base-machine', status='active')
            rows = [dict(common, id='kit', editable=False, decision='allow', resources=sorted(network.KIT_HOSTS)),
                    dict(common, id='original', editable=True, decision='deny', resources=['**'])]
            inventory = [dict(entry, status='stopped') for entry in registration['roles'].values()]
            inventory.append(dict(name='e-base-validation', id=recovery.VALIDATOR_ID, status='stopped'))
            atomic_write_json(base / 'policy.json', dict(rules=rows, inventory=inventory, serial=0))
            original_fence = fence_path.read_bytes()
            code = ('import sys; sys.path.insert(0,sys.argv[1]); '
                    'from test_network_process_crash import worker; worker(sys.argv[2],sys.argv[3])')
            child = subprocess.Popen([sys.executable, '-I', '-c', code, str(Path(__file__).resolve().parent),
                                      str(base), case], stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                deadline = time.monotonic() + 10
                while not (base / 'ready.json').is_file():
                    if child.poll() is not None:
                        self.fail('Synthetic worker exited before ready')
                    if time.monotonic() >= deadline:
                        self.fail('Synthetic worker readiness deadline')
                    time.sleep(0.02)
                journal_path = run / 'network-window/network-window.json'
                original_journal = journal_path.read_bytes()
                self.assertEqual(json.loads(original_journal)['phase'], case)
                child.kill()
                child.wait(timeout=3)
                self.assertEqual(child.returncode, -signal.SIGKILL)
                crashed_policy=json.loads((base/'policy.json').read_bytes())
                network.validate_rules(crashed_policy['rules'],'e-base-machine',model_access=True)
                self.assertEqual(journal_path.read_bytes(), original_journal)
                self.assertEqual(fence_path.read_bytes(), original_fence)
                with self.assertRaises(ValueError):
                    inspect_windows(root, registration)
                # STOP is deliberately placed after the crash, then retained by
                # the explicit deny-only recovery, never removed to resume work.
                stop = root / 'STOP'
                stop.write_bytes(b'operator hold')
                with isolation_patches(base):
                    result = recovery.recover(registration, 'machine', transport=FakeTransport(base))
                self.assertEqual(result['phase'], 'closed_recovery')
                self.assertEqual(inspect_windows(root, registration), {'machine': 'recovered_closed'})
                self.assertEqual(journal_path.read_bytes(), original_journal)
                self.assertEqual(fence_path.read_bytes(), original_fence)
                self.assertEqual(stop.read_bytes(), b'operator hold')
                state = json.loads((base / 'policy.json').read_bytes())
                self.assertTrue(any(row['resources'] == ['**'] for row in state['rules']))
            finally:
                if child.poll() is None:
                    child.kill()
                child.wait(timeout=3)

    def test_sigkill_after_open_requires_explicit_closed_recovery(self):
        self.run_case('open')

    def test_sigkill_after_removal_before_open_record_requires_recovery(self):
        self.run_case('opening')


if __name__ == '__main__':
    unittest.main()
