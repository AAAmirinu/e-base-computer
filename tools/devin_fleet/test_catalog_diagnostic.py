"""Trusted synthetic guest bootstrap tests, never invokes Devin."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import catalog_diagnostic as diagnostic
import model_catalog_policy
import mcp_maintenance_restart as guard


class DiagnosticTests(unittest.TestCase):
    def test_existing_reservation_refuses_before_runtime(self):
        registration={'production_enabled':False,'roles':{'machine':{'id':diagnostic.MACHINE}}}
        with tempfile.TemporaryDirectory() as directory,patch.object(diagnostic,'CATALOG_RUN',Path(directory)),\
             patch.object(diagnostic,'require_managed_namespace'),patch.object(diagnostic,'SandboxRuntime') as runtime:
            with self.assertRaises(FileExistsError):diagnostic.run_diagnostic(registration)
            runtime.assert_not_called()

    def test_catalog_partial_reservation_is_also_a_restart_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);run=root/'catalog';run.mkdir(mode=0o700)
            p=patch.object(guard,'DISCOVERY_RUN',root/'absent-discovery');p.start();self.addCleanup(p.stop)
            p=patch.object(guard,'FOURTH_CATALOG_RUN',root/'absent-fourth');p.start();self.addCleanup(p.stop)
            with patch.object(guard,'PREVIOUS_RUN',root/'absent-mcp-v1'),patch.object(guard,'RUN',root/'absent-mcp'),patch.object(guard,'CATALOG_RUN',run),patch.object(guard,'PREVIOUS_CATALOG_RUN',root/'absent-previous'),patch.object(guard,'SECOND_CATALOG_RUN',root/'absent-second'),patch.object(guard,'THIRD_CATALOG_RUN',root/'absent-third'):
                with self.assertRaises(OSError):guard.require_closed_maintenance(None)

    def guest(self,timeout=False):
        override='''import json
pairs=dict
def read_global(name):return b'{}'
def overrides(raw):return {'inherited':{'command':'/usr/bin/false','disabled':True},'fleet-probe':{}}
'''
        identity="CLI='/fixed/devin';calls=0\ndef verify_cli():\n global calls\n calls+=1\n"
        capture='''import json
from pathlib import Path
class CaptureDeadline(TimeoutError):
    observation={'leader_exited':False,'stdout_bytes':0,'stderr_bytes':0,'open_streams':['err','out']}
def _capture(argv,cwd,*,timeout,diagnostic=False):
    root=Path(cwd)
    assert argv==['/fixed/devin','--config',str(root/'config.json'),'models','list','--format','json']
    assert timeout==60 and diagnostic is True
    assert json.loads((root/'config.json').read_bytes())['permissions']['allow']==[]
    assert json.loads((root/'.devin/mcp_config.json').read_bytes())=={'mcpServers':{'inherited':{'command':'/usr/bin/false','disabled':True}}}
    assert not (root/'prompt.txt').exists()
'''
        if timeout=='rejected':capture+='    raise ValueError("SECRET")\n'
        else:capture+=('    raise CaptureDeadline()\n' if timeout else "    return b'{\"families\":[{\"variants\":[{\"model_uid\":\"swe-2-high\",\"cost_tier\":\"Free\"}]}]}',0\n")
        # Keep synthetic temp artifacts within one disposable test directory.
        with tempfile.TemporaryDirectory(dir='/tmp') as directory:
            source=diagnostic.PROBE.replace("dir='/tmp'",'dir='+repr(directory))
            result=subprocess.run([sys.executable,'-I','-c',source,override,identity,capture,
                                   Path(model_catalog_policy.__file__).read_text(),
                                   'def probe_endpoints():return {"synthetic": True}',json.dumps(diagnostic.DENY)],
                                  capture_output=True,timeout=5)
            self.assertEqual(result.returncode,0,result.stderr.decode())
            return json.loads(result.stdout.decode().removeprefix('EBASE_CATALOG_DIAGNOSTIC:'))

    def test_guest_fixed_catalog_has_no_model_prompt_or_fixture(self):
        value=self.guest();self.assertTrue(value['catalog_verified']);self.assertFalse(value['model_executed'])
        self.assertEqual(value['endpoints'],{'synthetic':True})

    def test_guest_timeout_returns_only_finite_observation(self):
        value=self.guest(True);self.assertFalse(value['catalog_verified'])
        self.assertEqual(value['error_type'],'CaptureDeadline');self.assertFalse(value['model_executed'])

    def test_rejection_retains_endpoints_without_exception_text(self):
        value=self.guest('rejected')
        self.assertFalse(value['catalog_verified'])
        self.assertEqual(value['endpoints'],{'synthetic':True})
        self.assertEqual(value['error_type'],'CatalogUnavailableOrRejected')
        self.assertNotIn('SECRET',json.dumps(value))


if __name__=='__main__':unittest.main()
