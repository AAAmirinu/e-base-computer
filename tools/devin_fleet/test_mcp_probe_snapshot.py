import os
from pathlib import Path
import shutil
import tempfile
import unittest
from mcp_probe_inputs import build_inputs
from mcp_probe_reservation import prepare_attempt
from mcp_probe_snapshot import snapshot


class SnapshotTests(unittest.TestCase):
    def test_git_root_change_and_extra_local_override_refused(self):
        head=self.work/'.git/HEAD'
        original=head.read_bytes()
        head.write_bytes(b'ref: refs/heads/other\n')
        with self.assertRaises(ValueError): snapshot(self.work,self.reservation,stage='before')
        head.write_bytes(original)
        (self.work/'.devin/config.local.json').touch(mode=0o600)
        with self.assertRaises(ValueError): snapshot(self.work,self.reservation,stage='before')

    def setUp(self):
        state = tempfile.TemporaryDirectory(prefix='mcp-snapshot-test-', dir='/tmp')
        self.addCleanup(state.cleanup)
        self.work, self.reservation = prepare_attempt(state.name, build_inputs, previous_sessions=[])
        self.addCleanup(shutil.rmtree, self.work)

    def test_before_and_after_capture(self):
        before = snapshot(self.work, self.reservation, stage='before')
        self.assertEqual(before['audit_raw'], b'')
        self.assertIsNone(before['export_raw'])
        target = self.work/'export.json'
        target.touch(mode=0o600)
        target.write_bytes(b'{"session_id":"synthetic"}')
        after = snapshot(self.work, self.reservation, stage='after')
        self.assertEqual(before['inputs'], after['inputs'])
        self.assertEqual(after['export_raw'], target.read_bytes())

    def test_existing_export_including_dangling_link_refused(self):
        (self.work/'export.json').symlink_to(self.work/'missing')
        with self.assertRaises(ValueError): snapshot(self.work, self.reservation, stage='before')

    def test_changed_input_and_used_audit_refused(self):
        path = self.work/'prompt.txt'
        original = path.read_bytes()
        path.write_bytes(b'changed')
        with self.assertRaises(ValueError): snapshot(self.work, self.reservation, stage='before')
        path.write_bytes(original)
        (self.work/'fixture-events.log').write_bytes(b'used')
        with self.assertRaises(ValueError): snapshot(self.work, self.reservation, stage='before')

    def test_hardlink_and_fifo_rejected(self):
        path = self.work/'prompt.txt'
        os.link(path, self.work/'alias')
        with self.assertRaises(ValueError): snapshot(self.work, self.reservation, stage='before')
        path.unlink()
        os.mkfifo(path, mode=0o600)
        with self.assertRaises(ValueError): snapshot(self.work, self.reservation, stage='before')

    def test_audit_replacement_rejected(self):
        path = self.work/'fixture-events.log'
        path.rename(self.work/'old-audit')
        path.touch(mode=0o600)
        with self.assertRaises(ValueError): snapshot(self.work, self.reservation, stage='before')

    def test_config_directory_symlink_rejected(self):
        path = self.work/'.devin'
        path.rename(self.work/'other')
        path.symlink_to(self.work/'other', target_is_directory=True)
        with self.assertRaises(OSError): snapshot(self.work, self.reservation, stage='before')


if __name__ == '__main__': unittest.main()
