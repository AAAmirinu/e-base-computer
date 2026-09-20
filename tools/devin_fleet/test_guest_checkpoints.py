from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import fleet
from sandbox_repository import GuestRepository
from sandbox_control import SandboxFenced


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = GuestRepository(Mock(), '/home/agent/workspace/machine', Path(self.tmp.name))
        self.repo.read_bytes = Mock()

    def test_object_read_without_host_fallback(self):
        self.repo.read_bytes.return_value = b'{"summary":"ready", "evidence":["unverified"]}'
        with patch.object(fleet, 'read', side_effect=AssertionError('host read')):
            result = fleet.read_repository_json(self.repo, '.fleet/report.json', {})
        self.assertEqual(result['summary'], 'ready')
        self.repo.read_bytes.assert_called_once_with('.fleet/report.json', max_bytes=1024 * 1024)
        self.repo.controller.stop.assert_not_called()

    def test_invalid_json_never_becomes_checkpoint(self):
        for data in (b'[]', b'null', b'{', b'\xff', b'{"x":1,"x":2}',
                     b'{"x":NaN}', b'{"x":{"a":1,"a":2}}', b'{"x":1e999}'):
            self.repo.read_bytes.return_value = data
            with self.subTest(data=data), self.assertRaises((ValueError, UnicodeError)):
                fleet.read_repository_json(self.repo, '.fleet/report.json', {})
        self.assertEqual(self.repo.controller.stop.call_count, 8)

    def test_fence_is_not_replaced_by_empty_default(self):
        self.repo.read_bytes.side_effect = SandboxFenced('STOP')
        with self.assertRaises(SandboxFenced):
            fleet.read_repository_json(self.repo, '.fleet/report.json', {})
        self.repo.controller.resume.assert_not_called()

    def test_legacy_missing_file_retains_default(self):
        self.assertEqual(fleet.read_repository_json(Path(self.tmp.name), 'missing.json', {}), {})


if __name__ == '__main__':
    unittest.main()
