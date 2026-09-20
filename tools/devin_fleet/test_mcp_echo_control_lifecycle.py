import unittest
from unittest.mock import patch
import mcp_echo_control_lifecycle as control
import mcp_probe_lifecycle as flow
import test_mcp_probe_lifecycle as fixtures
from test_mcp_wildcard_denial_evidence import sequence, audit, NONCE
from mcp_echo_control_evidence import summarize, MARKER


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
        for name, value in (('execute', execute), ('echo_control_network', flow.machine_probe_network)):
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
