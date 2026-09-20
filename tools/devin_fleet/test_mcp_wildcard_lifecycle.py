import unittest
from unittest.mock import patch
import mcp_wildcard_lifecycle as wildcard
import mcp_probe_lifecycle as flow
import test_mcp_probe_lifecycle as fixtures
from test_mcp_wildcard_denial_evidence import sequence, audit, NONCE
from mcp_wildcard_denial_evidence import summarize


class WildcardLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.LifecycleTests()
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        def execute(repo, action, **kwargs):
            result = self.fixture.execute(repo, action, **kwargs)
            if action != 'collect': return result
            result['tool_call_count'] = 2
            return {'binding': result, 'wildcard': summarize(sequence(), audit(), NONCE)}
        for name, value in (('execute', execute), ('wildcard_probe_network', flow.machine_probe_network)):
            p = patch.object(wildcard, name, value); p.start(); self.addCleanup(p.stop)

    def test_ordered_stops_and_bound_collection(self):
        result = wildcard.run_wildcard(self.fixture.registration)
        events = self.fixture.events
        self.assertLess(events.index('close'), events.index('stop1'))
        self.assertLess(events.index('stop1'), events.index('collect'))
        self.assertLess(events.index('collect'), events.index('stop2'))
        self.assertTrue(result['all_vms_stopped'])
        self.assertTrue(result['collection']['wildcard']['consistent'])
        self.assertFalse(result['permission_denial_accepted'])
        self.assertFalse(result['passed'])

    def test_dispatch_failure_closes_and_stops(self):
        self.fixture.fail = 'dispatch'
        with self.assertRaises(RuntimeError): wildcard.run_wildcard(self.fixture.registration)
        self.assertIn('close', self.fixture.events)
        self.assertIn('stop1', self.fixture.events)
        self.assertNotIn('collect', self.fixture.events)

    def test_bad_stop_hash_still_stops_inspection(self):
        self.fixture.fail = 'hash'
        with self.assertRaises(ValueError): wildcard.run_wildcard(self.fixture.registration)
        self.assertIn('stop2', self.fixture.events)


if __name__ == '__main__': unittest.main()
