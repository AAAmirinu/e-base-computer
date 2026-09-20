import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from mcp_probe_binding import ARTIFACTS, digest
from mcp_probe_reservation import CLAIM, prepare_attempt


class ReservationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='mcp-reservation-test-', dir='/tmp')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.root.chmod(0o700)
        self.inputs = {key: b'synthetic fixed input' for key in ARTIFACTS}

    def builder(self, work, nonce, identity):
        self.addCleanup(shutil.rmtree, work)
        self.assertEqual(len(nonce), 32)
        self.assertEqual(identity, (work.joinpath('fixture-events.log').stat().st_dev,
                                    work.joinpath('fixture-events.log').stat().st_ino))
        return self.inputs

    def test_prepares_private_bound_inputs_and_refuses_repeat(self):
        work, record = prepare_attempt(self.root, self.builder, previous_sessions=['old'])
        saved = json.loads((self.root/CLAIM/'reservation.json').read_bytes())
        self.assertEqual(saved, record)
        for name, raw in self.inputs.items():
            self.assertEqual((work/name).read_bytes(), raw)
            self.assertEqual((work/name).stat().st_mode & 0o777, 0o600)
            self.assertEqual(record['input_sha256'][name], digest(raw))
        with self.assertRaises(FileExistsError):
            prepare_attempt(self.root, self.builder, previous_sessions=[])

    def test_failure_keeps_claim_and_refuses_repeat(self):
        def fail(work, nonce, identity):
            self.addCleanup(shutil.rmtree, work)
            raise RuntimeError('synthetic interruption')
        with self.assertRaises(RuntimeError):
            prepare_attempt(self.root, fail, previous_sessions=[])
        self.assertTrue((self.root/CLAIM/'attempt.json').exists())
        self.assertFalse((self.root/CLAIM/'reservation.json').exists())
        with self.assertRaises(FileExistsError):
            prepare_attempt(self.root, self.builder, previous_sessions=[])

    def test_partial_claim_refuses_before_builder(self):
        (self.root/CLAIM).mkdir(mode=0o700)
        with patch.object(self, 'builder') as builder:
            with self.assertRaises(FileExistsError):
                prepare_attempt(self.root, builder, previous_sessions=[])
            builder.assert_not_called()

    def test_symlink_or_nonprivate_state_refused(self):
        alias = self.root/'alias'
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(OSError): prepare_attempt(alias, self.builder, previous_sessions=[])
        self.root.chmod(0o755)
        with self.assertRaises(ValueError): prepare_attempt(self.root, self.builder, previous_sessions=[])

    def test_invalid_artifacts_leave_claim(self):
        self.inputs = {'unexpected': b'input'}
        with self.assertRaises(ValueError): prepare_attempt(self.root, self.builder, previous_sessions=[])
        self.assertTrue((self.root/CLAIM).exists())

    def test_preexisting_output_prevents_ready_reservation(self):
        def unexpected_output(work, nonce, identity):
            inputs = self.builder(work, nonce, identity)
            (work/'export.json').touch(mode=0o600)
            return inputs
        with self.assertRaises(ValueError):
            prepare_attempt(self.root, unexpected_output, previous_sessions=[])
        self.assertFalse((self.root/CLAIM/'reservation.json').exists())
        self.assertTrue((self.root/CLAIM/'attempt.json').exists())

    def test_process_exit_preserves_claim_and_blocks_new_process(self):
        code = """import os,sys
sys.path.insert(0,sys.argv[1])
from mcp_probe_reservation import prepare_attempt
def interrupted(work,nonce,identity):
    os._exit(73)
prepare_attempt(sys.argv[2],interrupted,previous_sessions=[])
"""
        child = subprocess.run([sys.executable, '-I', '-c', code,
                                str(Path(__file__).parent), str(self.root)],
                               capture_output=True, timeout=10)
        self.assertEqual(child.returncode, 73)
        locator = json.loads((self.root/CLAIM/'attempt.json').read_bytes())
        work = Path(locator['work'])
        # Only this child's fixed-prefix, direct /tmp test directory is removed.
        self.assertEqual(work.parent, Path('/tmp'))
        self.assertTrue(work.name.startswith('e-base-mcp-probe-'))
        self.addCleanup(shutil.rmtree, work)
        again = subprocess.run([sys.executable, '-I', '-c', code,
                                str(Path(__file__).parent), str(self.root)],
                               capture_output=True, timeout=10)
        self.assertNotEqual(again.returncode, 73)
        self.assertIn(b'FileExistsError', again.stderr)
        self.assertFalse((self.root/CLAIM/'reservation.json').exists())


if __name__ == '__main__': unittest.main()
