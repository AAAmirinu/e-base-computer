import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import mcp_probe_collect as collector
from mcp_probe_supervision import MARKER,MACHINE
import test_mcp_probe_binding as fixtures


class CollectTests(unittest.TestCase):
    def write(self,name,value):
        path=self.claim/name; path.write_text(json.dumps(value)); path.chmod(0o600)
        return path.read_bytes()

    def setUp(self):
        temp=tempfile.TemporaryDirectory(dir='/tmp'); self.addCleanup(temp.cleanup)
        self.state=Path(temp.name); (self.state/'prepare-only').touch(mode=0o600)
        self.claim=self.state/collector.CLAIM; self.claim.mkdir(mode=0o700)
        self.f=fixtures.BindingTests(); self.f.setUp()
        raw=self.write('reservation.json',self.f.reservation)
        self.work='/tmp/e-base-mcp-probe-12345678'
        self.admission=dict(schema=2,nonce=self.f.nonce,reservation_sha256=collector.sha(raw),work=self.work,
                            machine_vm_id=MACHINE,lease_id='b'*32,issued_at=100,expires_at=200,
                            session_inventory_scope='current_workdir',session_inventory_verified=True,
                            fresh_attempt_preconditions_verified=True,previous_sessions=['old-session'])
        admitted=self.write(MARKER,self.admission)
        self.write('attempt.json',dict(nonce=self.f.nonce,work=self.work,phase='preparing'))
        argv=[collector.CLI,'--config',self.work+'/config.json','--model',collector.MODEL,
              '--permission-mode','normal','--respect-workspace-trust','false','--export',self.work+'/export.json',
              '--print',self.f.inputs['prompt.txt'].decode()]
        self.launch=dict(nonce=self.f.nonce,phase='attempted',model=collector.MODEL,main_config_sha256='1'*64,
                         catalog_sha256='2'*64,resume_used=False,work=self.work,input_sha256=self.f.reservation['input_sha256'],
                         reservation_sha256=collector.sha(raw),argv_sha256=collector.sha(json.dumps(argv).encode()),
                         supervision=dict(receipt=self.admission,receipt_sha256=collector.sha(admitted)))
        self.write('launch.json',self.launch)
        self.process=dict(returncode=0,timed_out=False,leader_reaped=True,process_group_stop_requested=True,
                          all_descendants_stopped=False,raw_output_suppressed=True,nonce=self.f.nonce,
                          phase='awaiting_vm_stop',passed=False,production_admitted=False,resume_used=False)
        self.write('process-result.json',self.process)
        self.stop=dict(schema=1,machine_vm_id=MACHINE,model_lease_id='b'*32,nonce=self.f.nonce,
                       reservation_sha256=collector.sha(raw),model_vm_stopped=True,network_denied=True)
        p=patch.object(collector,'snapshot',return_value=dict(inputs=self.f.inputs,audit_raw=self.f.audit,
                     export_raw=self.f.export,audit_identity=[1,2])); self.snapshot=p.start(); self.addCleanup(p.stop)

    def collect(self,inspection='c'*32):
        return collector.collect(json.dumps(self.stop).encode(),inspection_lease_id=inspection,state_directory=self.state)

    def test_binds_without_claiming_live_acceptance(self):
        result=self.collect()
        self.assertTrue(result['permission_denial_observed'])
        self.assertFalse(result['passed']); self.assertFalse(result['live_execution_verified'])
        self.assertFalse(result['inspection_vm_stopped'])
        self.assertNotIn('session_id',result)
        self.assertNotIn('new-synthetic-session',json.dumps(result))
        self.snapshot.assert_called_once_with(self.work,self.f.reservation,stage='after')

    def test_same_lease_and_unstopped_receipt_refused(self):
        with self.assertRaises(ValueError): self.collect('b'*32)
        self.stop['model_vm_stopped']=False
        with self.assertRaises(ValueError): self.collect()
        self.snapshot.assert_not_called()

    def test_argv_or_process_mismatch_refused(self):
        self.launch['argv_sha256']='0'*64; self.write('launch.json',self.launch)
        with self.assertRaises(ValueError): self.collect()
        self.process['returncode']=False; self.write('process-result.json',self.process)
        with self.assertRaises(ValueError): self.collect()

    def test_foreign_outer_binding_refused_before_capture(self):
        self.stop['reservation_sha256']='0'*64
        with self.assertRaises(ValueError): self.collect()
        self.snapshot.assert_not_called()

    def test_partial_claim_refused(self):
        (self.claim/'process-result.json').unlink()
        with self.assertRaises(ValueError): self.collect()
        self.snapshot.assert_not_called()


if __name__=='__main__': unittest.main()
