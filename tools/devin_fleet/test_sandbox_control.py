"""Transport contract tests only; fake processes do not attest VM isolation."""
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from unittest import mock

from sandbox_control import LinuxTransport, SandboxController, SandboxError, SandboxFenced

SANDBOX_ID = "40e32a36-d565-4853-a841-fa3bea9ac648"


class FakeProcess:
    def __init__(self, result=None):
        self.result = result

    def poll(self):
        return self.result


class FakeTransport:
    def __init__(self):
        self.events = []
        self.result = 0
        self.status = "stopped"
        self.rows = None
        self.fail_stop = False
        self.fail_spawn = False
        self.spawn_entered = threading.Event()
        self.spawn_release = None

    def spawn(self, argv, log):
        self.events.append(("spawn", argv))
        self.spawn_entered.set()
        if self.spawn_release is not None:
            if not self.spawn_release.wait(3):
                raise RuntimeError("test barrier timeout")
        if self.fail_spawn:
            raise OSError("failed spawn")
        return FakeProcess(self.result)

    def cancel(self, proc, timeout):
        self.events.append(("cancel", timeout))
        proc.result = -9

    def control(self, argv, timeout):
        self.events.append((argv[1], argv))
        if argv[1] == "stop":
            return subprocess.CompletedProcess(argv, int(self.fail_stop), "", "")
        rows = self.rows if self.rows is not None else [{"name": "e-base-machine", "id": SANDBOX_ID, "status": self.status}]
        return subprocess.CompletedProcess(argv, 0, json.dumps({"sandboxes": rows}), "")


class SandboxControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.transport = FakeTransport()
        self.controller = SandboxController("e-base-machine", self.root / "STOP", sandbox_id=SANDBOX_ID, transport=self.transport)

    def execute(self, name="run.log", timeout=1):
        return self.controller.execute(["python3", "-c", "print('guest')"], cwd="/workspace", log_path=self.root / name, timeout=timeout)

    def test_initial_fence_and_explicit_resume(self):
        with self.assertRaises(SandboxFenced):
            self.execute()
        self.controller.resume()
        self.assertEqual(self.execute().returncode, 0)
        argv = [event[1] for event in self.transport.events if event[0] == "spawn"][0]
        self.assertEqual(argv[:6], ["/usr/bin/sbx", "exec", "-w", "/workspace", "e-base-machine", "python3"])

    def test_stop_blocks_future_calls_until_resume(self):
        self.controller.resume()
        self.controller.stop()
        self.assertTrue((self.root / "STOP").exists())
        with self.assertRaises(SandboxFenced):
            self.execute()
        self.controller.resume()
        self.assertFalse((self.root / "STOP").exists())
        self.assertEqual(self.execute().returncode, 0)

    def test_timeout_cancels_client_before_vm_stop(self):
        self.controller.resume()
        self.transport.result = None
        with self.assertRaisesRegex(SandboxFenced, "timed out"):
            self.execute(timeout=0.03)
        events = [e[0] for e in self.transport.events]
        self.assertLess(events.index("cancel"), events.index("stop"))
        self.assertTrue(self.controller.fenced)

    def test_external_stop_file(self):
        self.controller.resume()
        (self.root / "STOP").touch()
        with self.assertRaises(SandboxFenced):
            self.execute()
        self.assertFalse(any(e[0] == "spawn" for e in self.transport.events))

    def test_excessive_output_stops_even_if_client_exited(self):
        self.controller.resume()
        def noisy(argv, log):
            log.write(b"12345")
            log.flush()
            return FakeProcess(0)
        with mock.patch.object(self.transport, "spawn", side_effect=noisy):
            with self.assertRaisesRegex(SandboxFenced, "log limit"):
                self.controller.execute(["true"], cwd="/workspace",
                    log_path=self.root / "large.log", timeout=1, max_log_bytes=4)
        self.assertTrue(self.controller.fenced)
        self.assertIn("stop", [e[0] for e in self.transport.events])

    def test_failed_stop_remains_fenced(self):
        self.controller.resume()
        self.transport.fail_stop = True
        with self.assertRaises(SandboxError):
            self.controller.stop()
        with self.assertRaises(SandboxFenced):
            self.execute()

    def test_stopped_verification_fail_closed(self):
        for rows in ([], [{"name": "other", "status": "stopped"}],
                     [{"name": "e-base-machine", "status": "running"}],
                     [{"name": "e-base-machine", "state": "stopped"}],
                     [{"name": "e-base-machine", "status": "stopped"}] * 2):
            with self.subTest(rows=rows):
                self.transport.rows = [dict(row, id=SANDBOX_ID) for row in rows]
                with self.assertRaises(SandboxError):
                    self.controller.resume()
                self.assertTrue(self.controller.fenced)

    def test_failed_spawn_stops_and_fences(self):
        self.controller.resume()
        self.transport.fail_spawn = True
        with self.assertRaises(OSError):
            self.execute()
        self.assertTrue(self.controller.fenced)
        self.assertIn("stop", [e[0] for e in self.transport.events])

    def test_validation(self):
        for identity in (None, "", "not-a-uuid", SANDBOX_ID.upper()):
            with self.assertRaises(ValueError):
                SandboxController("e-base-machine", self.root / "STOP",
                                  sandbox_id=identity, transport=self.transport)
        for timeout in (0, -1, float("nan"), float("inf"), True):
            with self.assertRaises(ValueError):
                self.execute(timeout=timeout)
        for name in ("--all", "other", "e-base-../bad", "e-base-x;ls"):
            with self.assertRaises(ValueError):
                SandboxController(name, self.root / "STOP", sandbox_id=SANDBOX_ID, transport=self.transport)

    def test_replacement_is_neither_executed_nor_stopped(self):
        self.controller.resume()
        self.transport.rows = [{"name": "e-base-machine", "status": "stopped",
                                "id": "00000000-0000-0000-0000-000000000000"}]
        with self.assertRaises(SandboxError):
            self.execute()
        self.assertTrue(self.controller.fenced)
        self.assertFalse(any(e[0] in ("spawn", "stop") for e in self.transport.events))

    def test_stop_refuses_same_name_different_id(self):
        self.controller.resume()
        self.transport.rows = [{"name": "e-base-machine", "status": "running"}]
        with self.assertRaises(SandboxError):
            self.controller.stop()
        self.assertTrue((self.root / "STOP").exists())
        self.assertFalse(any(e[0] == "stop" for e in self.transport.events))

    def test_transport_linux_only(self):
        with mock.patch("sandbox_control.sys.platform", "darwin"):
            with self.assertRaises(SandboxError):
                LinuxTransport()

    def test_transport_strips_desktop_and_agent_environment(self):
        env = {key: "secret" for key in ("DISPLAY", "WAYLAND_DISPLAY", "PULSE_SERVER",
               "SSH_AUTH_SOCK", "SSH_AGENT_PID", "DBUS_SESSION_BUS_ADDRESS")}
        env.update(HOME="/home/fleet", XDG_RUNTIME_DIR="/run/user/1000")
        with mock.patch.dict("sandbox_control.os.environ", env, clear=True):
            cleaned = LinuxTransport._environment()
        self.assertEqual(cleaned, {"HOME": "/home/fleet", "XDG_RUNTIME_DIR": "/run/user/1000"})

    def test_queued_exec_cannot_restart_after_stop(self):
        self.controller.resume()
        self.transport.result = None
        self.transport.spawn_release = threading.Event()
        errors = []

        def run(name):
            try:
                self.execute(name, timeout=2)
            except SandboxError as exc:
                errors.append(exc)

        first = threading.Thread(target=run, args=("one.log",))
        queued = threading.Thread(target=run, args=("two.log",))
        stopper = threading.Thread(target=self.controller.stop)
        first.start()
        self.assertTrue(self.transport.spawn_entered.wait(1))
        queued.start()
        stopper.start()
        deadline = time.monotonic() + 1
        while not self.controller.fenced and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertTrue(self.controller.fenced)
        self.transport.spawn_release.set()
        for thread in (first, queued, stopper):
            thread.join(3)
            self.assertFalse(thread.is_alive())
        self.assertEqual(len([e for e in self.transport.events if e[0] == "spawn"]), 1)
        events = [e[0] for e in self.transport.events]
        self.assertLess(events.index("cancel"), events.index("stop"))
        self.assertEqual(len(errors), 2)
        self.assertTrue(self.controller.fenced)


if __name__ == "__main__":
    unittest.main()
