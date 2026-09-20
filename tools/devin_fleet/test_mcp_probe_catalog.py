import sys
import tempfile
import unittest
from unittest.mock import patch
import mcp_probe_catalog as catalog


class CatalogTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='mcp-catalog-test-',dir='/tmp')
        self.addCleanup(temporary.cleanup)
        self.root=temporary.name

    def run_code(self,code,timeout=3):
        return catalog._capture([sys.executable,'-I','-c',code],self.root,timeout=timeout)

    def test_stdout_only_and_nonzero_preserved(self):
        raw,rc=self.run_code("import sys; print('catalog'); print('SECRET',file=sys.stderr); sys.exit(7)")
        self.assertEqual(raw,b'catalog\n')
        self.assertEqual(rc,7)

    def test_both_output_limits(self):
        for code in ("import sys; sys.stdout.write('x'*1100000)","import sys; sys.stderr.write('SECRET'*12000)"):
            with self.assertRaisesRegex(ValueError,'output limit'): self.run_code(code)

    def test_timeout(self):
        with self.assertRaises(TimeoutError): self.run_code('import time; time.sleep(30)',timeout=.2)

    def test_longer_wait_only_for_explicit_bounded_diagnostic(self):
        with self.assertRaises(ValueError):
            catalog._capture([sys.executable,'-c','pass'],self.root,timeout=21)
        with self.assertRaises(ValueError):
            catalog._capture([sys.executable,'-c','pass'],self.root,timeout=61,diagnostic=True)
        self.assertEqual(catalog._capture([sys.executable,'-c','pass'],self.root,timeout=60,diagnostic=True),(b'',0))

    def test_timeout_metadata_does_not_expose_output(self):
        with self.assertRaises(catalog.CaptureDeadline) as caught:
            self.run_code("import os,time; os.write(1,b'PRIVATE'); os.write(2,b'SECRET'); time.sleep(30)",timeout=1)
        self.assertEqual(caught.exception.observation,dict(leader_exited=False,
                         stdout_bytes=7,stderr_bytes=6,open_streams=['err','out']))
        self.assertNotIn('PRIVATE',str(caught.exception))
        self.assertNotIn('SECRET',str(caught.exception))

    def test_timeout_with_closed_pipes_still_reports_live_leader(self):
        with self.assertRaises(catalog.CaptureDeadline) as caught:
            self.run_code('import os,time; os.close(1); os.close(2); time.sleep(30)',timeout=1)
        self.assertEqual(caught.exception.observation,dict(leader_exited=False,
                         stdout_bytes=0,stderr_bytes=0,open_streams=[]))

    def test_fixed_cli_command(self):
        with patch.object(catalog,'_capture',return_value=(b'{}',0)) as capture:
            catalog.read_catalog('/tmp/e-base-mcp-probe-12345678')
        self.assertEqual(capture.call_args.args[0],[catalog.CLI,'--config','/tmp/e-base-mcp-probe-12345678/config.json','models','list','--format','json'])
        self.assertEqual(capture.call_args.kwargs,dict(timeout=60,diagnostic=True))
        with self.assertRaises(ValueError): catalog.read_catalog('/tmp/other')


if __name__=='__main__': unittest.main()
