"""Local process tests only: no network, Devin, or unrelated process signals."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from process_control import GlobalLock, LockUnavailable, RunInterrupted, global_lock_held, supervised_run


class ProcessControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fleet-process-control-")
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def wait_for(self, path, timeout=4):
        deadline = time.monotonic() + timeout
        while not path.exists():
            if time.monotonic() > deadline:
                self.fail(f"Process did not create {path}")
            time.sleep(0.05)

    def test_lock_file_is_not_liveness(self):
        lock = self.root / "runner.lock"
        lock.touch()
        self.assertFalse(global_lock_held(lock))
        with GlobalLock(lock):
            self.assertTrue(global_lock_held(lock))
            with self.assertRaises(LockUnavailable):
                with GlobalLock(lock):
                    pass
        self.assertFalse(global_lock_held(lock))

    def test_separate_process_lock_releases_after_exit(self):
        lock, ready = self.root / "runner.lock", self.root / "ready"
        code = ("from pathlib import Path; import sys,time; "
                f"sys.path.insert(0, {str(Path(__file__).resolve().parent)!r}); "
                "from process_control import GlobalLock; "
                f"lock=GlobalLock({str(lock)!r}); lock.__enter__(); "
                f"Path({str(ready)!r}).touch(); time.sleep(1)")
        proc = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            self.wait_for(ready)
            self.assertTrue(global_lock_held(lock))
            proc.wait(timeout=4)
            self.assertEqual(proc.returncode, 0)
            self.assertFalse(global_lock_held(lock))
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=4)
            proc.stderr.close()

    def test_large_combined_output_does_not_pipe_deadlock(self):
        result = supervised_run([sys.executable, "-c", "import sys; print('x'*200000); print('stderr-marker',file=sys.stderr); sys.exit(7)"],
                                self.root, self.root / "output.log", self.root / "STOP", 5)
        self.assertEqual(result.returncode, 7)
        self.assertGreater(len(result.stdout), 200000)
        self.assertIn("stderr-marker", result.stdout)
        self.assertEqual(result.stderr, "")

    def test_on_start_receives_owned_process(self):
        seen = []
        result = supervised_run([sys.executable, "-c", "print('ok')"],
                                self.root, self.root / "output.log", self.root / "STOP", 5,
                                on_start=lambda proc: seen.append(proc.pid))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(seen), 1)
        self.assertGreater(seen[0], 0)

    def test_existing_stop_prevents_launch(self):
        stop, marker = self.root / "STOP", self.root / "launched"
        stop.touch()
        with self.assertRaises(RunInterrupted) as caught:
            supervised_run([sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).touch()"],
                           self.root, self.root / "output.log", stop, 3)
        self.assertEqual(caught.exception.reason, "stop")
        self.assertFalse(marker.exists())

    def test_timeout_terminates_owned_child(self):
        started = time.monotonic()
        with self.assertRaises(RunInterrupted) as caught:
            supervised_run([sys.executable, "-c", "import time; print('started',flush=True); time.sleep(5)"],
                           self.root, self.root / "timeout.log", self.root / "STOP", 0.4)
        self.assertEqual(caught.exception.reason, "timeout")
        self.assertLess(time.monotonic() - started, 4)
        self.assertIn("started", (self.root / "timeout.log").read_text())

    def test_stop_terminates_owned_child_and_grandchild(self):
        stop, ready, heartbeat = self.root / "STOP", self.root / "ready", self.root / "heartbeat"
        # A grandchild updates a heartbeat; after tree stop it must stay still.
        child = ("import time; from pathlib import Path; "
                 f"p=Path({str(heartbeat)!r}); Path({str(ready)!r}).touch(); "
                 "\nfor n in range(100):\n p.write_text(str(n)); time.sleep(.05)")
        parent = f"import subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c',{child!r}]); time.sleep(6)"
        thread_errors = []
        def request_stop():
            try:
                self.wait_for(ready)
                self.wait_for(heartbeat)
                stop.touch()
            except BaseException as exc:
                thread_errors.append(exc)
        stopper = threading.Thread(target=request_stop)
        stopper.start()
        try:
            with self.assertRaises(RunInterrupted) as caught:
                supervised_run([sys.executable, "-c", parent], self.root, self.root / "tree.log", stop, 4)
            self.assertEqual(caught.exception.reason, "stop")
        finally:
            stopper.join(timeout=5)
        self.assertEqual(thread_errors, [])
        before = heartbeat.read_text()
        time.sleep(0.25)
        self.assertEqual(heartbeat.read_text(), before)


if __name__ == "__main__":
    unittest.main()
