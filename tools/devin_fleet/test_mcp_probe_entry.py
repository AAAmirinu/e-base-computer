from pathlib import Path
import signal
import subprocess
import sys
import unittest
from unittest.mock import patch
import mcp_probe_entry as entry


class EntryTests(unittest.TestCase):
    def test_unknown_action_never_enters_runtime(self):
        with patch.object(entry,'run_probe') as run:
            for args in ([],['--resume'],['--once','--once']):
                with self.assertRaises(ValueError): entry.main(args)
            run.assert_not_called()

    def test_handlers_restored_without_interruption(self):
        before={sig:signal.getsignal(sig) for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP)}
        with entry.interruption_cleanup(): pass
        self.assertEqual(before,{sig:signal.getsignal(sig) for sig in before})

    def test_real_signal_unwinds_and_repeated_cancel_does_not_abort_cleanup(self):
        script='''import os,signal,sys
sys.path.insert(0,sys.argv[1])
from mcp_probe_entry import interruption_cleanup
events=[]
before=signal.getsignal(signal.SIGTERM)
try:
    with interruption_cleanup():
        try:
            events.append('opened')
            os.kill(os.getpid(),signal.SIGTERM)
        finally:
            events.append('deny')
            os.kill(os.getpid(),signal.SIGTERM)
            events.append('stop')
except KeyboardInterrupt:
    events.append('interrupted')
assert events==['opened','deny','stop','interrupted']
assert signal.getsignal(signal.SIGTERM)==before
print('synthetic cleanup complete')
'''
        result=subprocess.run([sys.executable,'-I','-c',script,str(Path(__file__).parent)],
                              capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr.decode())
        self.assertEqual(result.stdout,b'synthetic cleanup complete\n')
