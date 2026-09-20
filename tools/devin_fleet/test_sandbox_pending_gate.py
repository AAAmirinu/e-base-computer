import json
from pathlib import Path
import tempfile
import unittest
from validation_pending_gate import unresolved_dispatches
import test_sandbox_dispatch_recovery as recovery_tests


class PendingGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / ('dispatch-' + 'a' * 32)
        self.path.mkdir(mode=0o700)
        self.fixture = recovery_tests.RecoveryTests()
        self.fixture.setUp()

    def write(self):
        (self.path / 'dispatch.json').write_text(json.dumps(self.fixture.journal))
        (self.path / 'stdout.log').write_bytes(self.fixture.output)

    def check(self):
        return unresolved_dispatches(self.root, 'vm', self.fixture.vm)

    def test_complete_bound_evidence_does_not_hold(self):
        self.write()
        self.assertEqual(self.check(), [])

    def test_all_unfinished_phases_hold(self):
        for phase in ('prepared', 'running', 'result_received', 'inspection_required', 'cleanup_failed'):
            self.fixture.journal['phase'] = phase
            self.write()
            self.assertEqual(self.check()[0]['reason'], 'incomplete_dispatch_phase')

    def test_missing_receipt_holds(self):
        self.assertEqual(self.check()[0]['reason'], 'missing_or_invalid_evidence')

    def test_forged_complete_and_changed_output_hold(self):
        self.write()
        (self.path / 'stdout.log').write_bytes(b'changed')
        self.assertEqual(len(self.check()), 1)

    def test_foreign_vm_holds(self):
        self.fixture.journal['sandbox_id'] = 'different'
        self.write()
        self.assertEqual(len(self.check()), 1)

    def test_does_not_mutate_evidence(self):
        self.fixture.journal['phase'] = 'running'
        self.write()
        before = (self.path / 'dispatch.json').read_bytes()
        self.check()
        self.assertEqual((self.path / 'dispatch.json').read_bytes(), before)

    def test_unrelated_directory_ignored(self):
        self.write()
        (self.root / 'unrelated').mkdir()
        self.assertEqual(self.check(), [])


if __name__ == '__main__':
    unittest.main()
