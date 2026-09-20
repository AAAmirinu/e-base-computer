"""Maintenance CLI boundaries; all VM operations are mocked."""
import argparse
from contextlib import ExitStack, redirect_stdout, redirect_stderr
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import sandbox_driver as driver


class DriverTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory())).resolve()
        self.root.chmod(0o700)
        self.registry = self.root / 'registry.json'
        self.registration = {'roles': {'machine': {'name': 'e-base-machine', 'id': 'id'}}}
        self.registry.write_text(json.dumps(self.registration), encoding='utf-8')
        self.runtime_type = self.stack.enter_context(patch.object(driver, 'SandboxRuntime'))
        self.runtime = self.runtime_type.return_value
        self.runtime.__enter__.return_value = self.runtime
        self.transport = Mock()
        self.inventory([{'name': 'e-base-machine', 'id': 'id', 'status': 'stopped'}])

    def inventory(self, rows):
        self.transport.control.return_value = argparse.Namespace(
            returncode=0, stdout=json.dumps({'sandboxes': rows}))

    def args(self, command='status'):
        return argparse.Namespace(command=command, root=str(self.root), registry=str(self.registry),
            receipt=str(self.root / 'receipt.json'), operation='a' * 32,
            evidence=str(self.root / 'new-evidence'))

    def inspect(self):
        args = self.args('inspect-sync')
        Path(args.receipt).write_bytes(b'{}')
        return args

    def test_status_only_lists_without_runtime_entry(self):
        result = driver.execute(self.args(), self.transport)
        self.assertEqual(result['roles']['machine'], 'stopped')
        self.assertFalse(result['resume_available'])
        self.transport.control.assert_called_once_with(['/usr/bin/sbx', 'ls', '--json'], 30)
        self.runtime.__enter__.assert_not_called()
        self.runtime.role.assert_not_called()

    def test_inspect_turns_is_local_only_and_preserves_stop(self):
        stop = self.root/'STOP'
        stop.write_bytes(b'operator stop')
        result = driver.execute(self.args('inspect-turns'), self.transport)
        self.assertFalse(result['resume_available'])
        self.assertFalse(result['runtime_state_observed'])
        self.assertTrue(all(item['state'] == 'absent' for item in result['roles'].values()))
        self.assertEqual(stop.read_bytes(), b'operator stop')
        self.assertFalse((self.root/'model-turn-fences').exists())
        self.runtime_type.assert_not_called()
        self.transport.control.assert_not_called()

    def test_status_running_missing_duplicate_replaced_unknown(self):
        row = {'name': 'e-base-machine', 'id': 'id', 'status': 'running'}
        for rows, expected in [([row], 'running'), ([], 'identity_or_state_mismatch'),
                ([row, row], 'identity_or_state_mismatch'),
                ([dict(row, id='replacement')], 'identity_or_state_mismatch'),
                ([dict(row, status='starting')], 'identity_or_state_mismatch')]:
            with self.subTest(rows=rows):
                self.inventory(rows)
                self.assertEqual(driver.execute(self.args(), self.transport)['roles']['machine'], expected)
        self.runtime.__enter__.assert_not_called()

    def test_bad_inventory_rejected(self):
        for raw in ['{', '[]', '{"sandboxes":{}}', '{"sandboxes":[1]}',
                    '{"sandboxes":[],"sandboxes":[]}', 'x' * (1024 * 1024 + 1)]:
            with self.subTest(raw=raw[:40]):
                self.transport.control.return_value.stdout = raw
                with self.assertRaises(ValueError):
                    driver.execute(self.args(), self.transport)
        self.runtime.__enter__.assert_not_called()

    def test_failed_inventory_rejected(self):
        self.transport.control.return_value.returncode = 1
        with self.assertRaises(ValueError):
            driver.execute(self.args(), self.transport)

    def test_stop_blocks_inspection_and_is_retained(self):
        args = self.inspect()
        stop = self.root / 'STOP'
        stop.write_bytes(b'stop')
        with self.assertRaisesRegex(ValueError, 'STOP'):
            driver.execute(args, self.transport)
        self.assertEqual(stop.read_bytes(), b'stop')
        self.runtime.__enter__.assert_not_called()
        self.assertTrue(driver.execute(self.args(), self.transport)['stop_requested'])

    def test_dangling_stop_blocks_inspection(self):
        args = self.inspect()
        stop = self.root / 'STOP'
        try:
            stop.symlink_to(self.root / 'nonexistent')
        except OSError:
            self.skipTest('Symlink creation unavailable')
        with self.assertRaisesRegex(ValueError, 'STOP'):
            driver.execute(args, self.transport)
        self.assertTrue(os.path.lexists(stop))
        self.runtime.__enter__.assert_not_called()

    def test_json_requires_unique_finite_object(self):
        for raw in [b'[]', b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}', b'{"a":1.1}', b'\xff']:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                driver._json(raw)
        self.assertEqual(driver._json(b'{"ok":1}'), {'ok': 1})

    def test_read_bound_and_absolute_regular_file(self):
        path = self.root / 'input'
        path.write_bytes(b'1234')
        self.assertEqual(driver._read(path, 4), b'1234')
        with self.assertRaises(ValueError):
            driver._read(path, 3)
        with self.assertRaises(ValueError):
            driver._read('relative')
        with self.assertRaises((ValueError, OSError)):
            driver._read(self.root)

    @unittest.skipUnless(hasattr(os, 'O_NOFOLLOW'), 'Linux no-follow boundary')
    def test_read_rejects_symlink(self):
        path = self.root / 'linked'
        path.symlink_to(self.registry)
        with self.assertRaises((ValueError, OSError)):
            driver._read(path)

    def test_evidence_must_be_fresh_direct_child(self):
        args = self.inspect()
        for path in [self.root, self.root / 'nested' / 'evidence', self.registry]:
            with self.subTest(path=path), patch.object(driver, '_receipt', return_value={}, create=True):
                args.evidence = str(path)
                with self.assertRaises(ValueError):
                    driver.execute(args, self.transport)
        self.runtime.__enter__.assert_not_called()

    def test_valid_inspection_delegates_exact_bytes_and_paths(self):
        args = self.inspect()
        with patch.object(driver, '_receipt', return_value={}, create=True), \
                patch.object(driver, 'inspect_sync_recovery', return_value={'replay_permitted': False}) as inspect:
            self.assertEqual(driver.execute(args, self.transport), {'replay_permitted': False})
        inspect.assert_called_once_with(self.runtime, b'{}', args.operation, Path(args.evidence))
        self.runtime.__enter__.assert_called_once()
        self.runtime.__exit__.assert_called_once()
        self.transport.control.assert_not_called()

    def test_invalid_receipt_rejected_before_runtime_entry(self):
        args = self.inspect()
        with patch.object(driver, '_receipt', side_effect=ValueError('invalid receipt'), create=True):
            with self.assertRaisesRegex(ValueError, 'invalid receipt'):
                driver.execute(args, self.transport)
        self.runtime.__enter__.assert_not_called()

    def test_cli_disallows_run_and_resume(self):
        for command in ['run', 'resume']:
            with self.subTest(command=command), redirect_stderr(io.StringIO()), \
                    patch.object(driver, '_dedicated_environment') as env, self.assertRaises(SystemExit):
                driver.main(['--registry', str(self.registry), '--root', str(self.root), command])
            env.assert_not_called()

    def test_main_checks_environment_before_execute(self):
        argv = ['--registry', str(self.registry), '--root', str(self.root), 'status']
        with patch.object(driver, '_dedicated_environment', side_effect=ValueError('wrong environment')), \
                patch.object(driver, 'execute') as execute, redirect_stderr(io.StringIO()) as error:
            self.assertEqual(driver.main(argv), 2)
            self.assertIn('wrong environment', error.getvalue())
            execute.assert_not_called()
        with patch.object(driver, '_dedicated_environment') as env, \
                patch.object(driver, 'execute', return_value={'ok': True}) as execute, \
                redirect_stdout(io.StringIO()) as output:
            self.assertEqual(driver.main(argv), 0)
        env.assert_called_once()
        execute.assert_called_once()
        self.assertEqual(json.loads(output.getvalue()), {'ok': True})


if __name__ == '__main__':
    unittest.main()
