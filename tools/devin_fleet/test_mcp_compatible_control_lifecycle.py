import unittest
from pathlib import Path
from types import SimpleNamespace
import tempfile
from unittest.mock import patch
import mcp_compatible_control_lifecycle as control
import mcp_probe_lifecycle as flow
import test_mcp_probe_lifecycle as fixtures
from test_mcp_wildcard_denial_evidence import sequence, audit, NONCE
from mcp_echo_control_evidence import summarize, MARKER


class CompatibleExecuteTests(unittest.TestCase):
    def test_fixed_sources_compiled_and_stage_arguments_forwarded(self):
        source_root = Path(__file__).parent
        with tempfile.TemporaryDirectory(dir='/tmp') as directory:
            logs = Path(directory)
            calls = []
            def execute(command, **kwargs):
                calls.append((command, kwargs))
                compile(command[3], '<compatible-stage>', 'exec')
                self.assertIn('prepare.STATE=prepare.COMPATIBLE_CONTROL_STATE', command[3])
                self.assertIn('inspect.inspect_compatible_control', command[3])
                kwargs['log_path'].write_text('EBASE_MCP_DISPATCH:{"ok":true}\n')
                kwargs['log_path'].chmod(0o600)
                return SimpleNamespace(returncode=0)
            repo = SimpleNamespace(log_dir=logs, external_stop=object(),
                                   controller=SimpleNamespace(execute=execute))
            with patch.object(control, 'ROOT', source_root), patch.object(control, '_lease', return_value='lease'):
                for action in ('preflight', 'dispatch', 'collect'):
                    self.assertEqual(control.execute(repo, action, timeout=17,
                        admission=b'admission', stop_raw=b'stop'), {'ok': True})
            self.assertEqual(calls[0][0][-1], 'preflight')
            self.assertEqual(calls[1][0][-2:], ['dispatch', 'admission'])
            self.assertEqual(calls[2][0][-3:], ['collect', 'stop', 'lease'])
            for action, (_, kwargs) in zip(('preflight', 'dispatch', 'collect'), calls):
                self.assertEqual(kwargs['log_path'].name, 'compatible-control-'+action+'.log')
                self.assertEqual(kwargs['timeout'], 17)
                self.assertEqual(kwargs['max_log_bytes'], 16384)
                self.assertIs(kwargs['external_stop'], repo.external_stop)

    def test_unknown_action_rejected_before_source_read(self):
        with patch.object(control, '_file') as read:
            with self.assertRaises(ValueError): control.execute(None, 'retry', timeout=1)
            read.assert_not_called()


class ControlLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.LifecycleTests()
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        def execute(repo, action, **kwargs):
            result = self.fixture.execute(repo, action, **kwargs)
            if action != 'collect': return result
            result.update(tool_call_count=2, execution_marker_seen=True,
                          linked_denial_observed=False, permission_denial_observed=False)
            data = sequence()
            data['steps'][3]['observation']['results'][0]['content'] = MARKER
            candidate = summarize(data, audit(('initialized', 'listed', 'called')), NONCE)
            return {'binding': result, 'control': candidate}
        for name, value in (('execute', execute), ('compatible_control_network', flow.machine_probe_network)):
            p = patch.object(control, name, value); p.start(); self.addCleanup(p.stop)

    def test_ordered_stops_and_bound_collection(self):
        result = control.run_control(self.fixture.registration)
        events = self.fixture.events
        self.assertLess(events.index('close'), events.index('stop1'))
        self.assertLess(events.index('stop1'), events.index('collect'))
        self.assertLess(events.index('collect'), events.index('stop2'))
        self.assertTrue(result['all_vms_stopped'])
        self.assertTrue(result['collection']['control']['consistent'])
        self.assertTrue(result['collection']['binding']['execution_marker_seen'])
        self.assertEqual(result['collection']['control']['audit_call_count'], 1)
        self.assertFalse(result['permission_denial_accepted'])
        self.assertFalse(result['passed'])
        self.assertFalse(result['production_admitted'])

    def test_dispatch_failure_closes_and_stops(self):
        self.fixture.fail = 'dispatch'
        with self.assertRaises(RuntimeError): control.run_control(self.fixture.registration)
        self.assertIn('close', self.fixture.events)
        self.assertIn('stop1', self.fixture.events)
        self.assertNotIn('collect', self.fixture.events)

    def test_bad_stop_hash_still_stops_inspection(self):
        self.fixture.fail = 'hash'
        with self.assertRaises(ValueError): control.run_control(self.fixture.registration)
        self.assertIn('stop2', self.fixture.events)


if __name__ == '__main__': unittest.main()
