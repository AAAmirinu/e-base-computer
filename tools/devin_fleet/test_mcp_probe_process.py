import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from mcp_probe_process import run_private_process


class ProcessTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='mcp-process-test-', dir='/tmp')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def run_code(self, code, timeout=3):
        return run_private_process([sys.executable, '-I', '-c', code], cwd=self.root, timeout=timeout)

    def test_exit_and_large_output_are_suppressed(self):
        result = self.run_code("import sys; print('x'*1000000); sys.exit(7)")
        self.assertEqual(result['returncode'], 7)
        self.assertTrue(result['leader_reaped'])
        self.assertTrue(result['raw_output_suppressed'])
        self.assertFalse(result['all_descendants_stopped'])
        self.assertFalse(result['timed_out'])

    def test_timeout_reaps_leader(self):
        started = time.monotonic()
        result = self.run_code('import time; time.sleep(30)', timeout=0.2)
        self.assertTrue(result['timed_out'])
        self.assertEqual(result['returncode'], -9)
        self.assertLess(time.monotonic()-started, 3)

    def test_child_stopped_even_after_leader_normal_exit(self):
        heartbeat = self.root/'heartbeat'
        child = ('import time; from pathlib import Path; '
                 f'p=Path({str(heartbeat)!r}); '
                 '\nfor n in range(100):\n p.write_text(str(n)); time.sleep(.03)')
        parent = ('import subprocess,sys,time; from pathlib import Path; '
                  f'subprocess.Popen([sys.executable,"-I","-c",{child!r}]); '
                  f'p=Path({str(heartbeat)!r}); '
                  '\nwhile not p.exists(): time.sleep(.01)')
        result = self.run_code(parent)
        self.assertEqual(result['returncode'], 0)
        self.assertTrue(result['process_group_stop_requested'])
        time.sleep(.1)
        before = heartbeat.read_bytes()
        time.sleep(.2)
        self.assertEqual(heartbeat.read_bytes(), before)

    def test_private_umask_and_closed_inheritable_fd(self):
        fd = os.open(self.root/'private', os.O_CREAT | os.O_WRONLY, 0o600)
        self.addCleanup(os.close, fd)
        os.set_inheritable(fd, True)
        code = (f'import os; from pathlib import Path; Path("created").touch(); '
                f'\ntry: os.fstat({fd})\nexcept OSError: pass\nelse: raise RuntimeError("FD inherited")')
        result = self.run_code(code)
        self.assertEqual(result['returncode'], 0)
        self.assertEqual((self.root/'created').stat().st_mode & 0o777, 0o600)

    def test_invalid_deadlines_refused(self):
        for value in (False, 0, -1, float('nan'), float('inf'), 91):
            with self.assertRaises(ValueError): self.run_code('pass', timeout=value)


if __name__ == '__main__': unittest.main()
