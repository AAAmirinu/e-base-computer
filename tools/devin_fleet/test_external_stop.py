"""Fleet STOP transport contracts; fake processes do not prove VM isolation."""
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

from sandbox_control import SandboxController, SandboxFenced
from test_sandbox_control import FakeTransport, SANDBOX_ID


class ExternalStopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.external_stop = self.root / "fleet-STOP"
        self.local_stop = self.root / "machine-STOP"
        self.transport = FakeTransport()
        self.controller = SandboxController(
            "e-base-machine", self.local_stop, sandbox_id=SANDBOX_ID,
            transport=self.transport)
        self.controller.resume()
        self.transport.events.clear()

    def execute(self):
        return self.controller.execute(
            ["true"], cwd="/workspace", log_path=self.root / "run.log",
            timeout=2, external_stop=self.external_stop)

    def test_existing_fleet_stop_rejects_before_spawn(self):
        self.external_stop.write_bytes(b"operator requested stop\n")
        with self.assertRaises(SandboxFenced):
            self.execute()
        self.assertFalse(any(event[0] == "spawn" for event in self.transport.events))
        self.assertEqual(self.external_stop.read_bytes(), b"operator requested stop\n")

    def test_stop_arriving_during_identity_check_prevents_spawn(self):
        original = self.transport.control

        def stop_during_identity(argv, timeout):
            result = original(argv, timeout)
            if argv[1] == "ls":
                self.external_stop.touch()
            return result

        with mock.patch.object(self.transport, "control", side_effect=stop_during_identity):
            with self.assertRaises(SandboxFenced):
                self.execute()
        self.assertFalse(any(event[0] == "spawn" for event in self.transport.events))
        self.assertTrue(self.controller.fenced)
        self.assertTrue(self.external_stop.exists())

    def test_running_command_is_cancelled_and_vm_stopped(self):
        self.transport.result = None
        errors = []

        def run():
            try:
                self.execute()
            except BaseException as exc:
                errors.append(exc)

        worker = threading.Thread(target=run)
        worker.start()
        try:
            self.assertTrue(self.transport.spawn_entered.wait(1), "guest command was not spawned")
            self.external_stop.write_bytes(b"stop while running\n")
        finally:
            worker.join(4)
        self.assertFalse(worker.is_alive(), "STOP did not finish execution")
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], SandboxFenced)
        # Ensure STOP, rather than the independent command timeout, caused exit.
        self.assertNotIn("timed out", str(errors[0]))
        events = [event[0] for event in self.transport.events]
        self.assertLess(events.index("cancel"), events.index("stop"))
        self.assertTrue(self.controller.fenced)
        self.assertTrue(self.local_stop.exists())
        self.assertEqual(self.external_stop.read_bytes(), b"stop while running\n")

    def test_explicit_resume_never_removes_fleet_stop(self):
        self.external_stop.write_bytes(b"persistent fleet fence\n")
        self.controller.stop()
        self.controller.resume()
        self.assertFalse(self.local_stop.exists())
        self.assertEqual(self.external_stop.read_bytes(), b"persistent fleet fence\n")
        self.transport.events.clear()
        with self.assertRaises(SandboxFenced):
            self.execute()
        self.assertFalse(any(event[0] == "spawn" for event in self.transport.events))

    def test_absent_fleet_stop_allows_normal_completion(self):
        self.assertEqual(self.execute().returncode, 0)
        self.assertEqual(sum(event[0] == "spawn" for event in self.transport.events), 1)
        self.assertFalse(any(event[0] in ("cancel", "stop") for event in self.transport.events))
        self.assertFalse(self.external_stop.exists())
        self.assertFalse(self.local_stop.exists())
        self.assertFalse(self.controller.fenced)


if __name__ == "__main__":
    unittest.main()
