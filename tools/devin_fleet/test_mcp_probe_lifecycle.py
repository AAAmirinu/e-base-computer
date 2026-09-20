from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import mcp_probe_lifecycle as flow


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(dir='/tmp'); self.addCleanup(temp.cleanup)
        self.root=Path(temp.name); self.events=[]; self.active=False; self.fail=None; self.roles=0
        self.registration=dict(production_enabled=False,roles={'machine':{'id':flow.MACHINE}})
        registry=self.root/'sandbox-registry.json'; registry.write_text(json.dumps(self.registration)); registry.chmod(0o600)
        self.pre=dict(nonce='a'*32,work='/tmp/e-base-mcp-probe-12345678',reservation_sha256='1'*64,
                      inventory=dict(work='/tmp/e-base-mcp-probe-12345678',session_inventory_scope='current_workdir',
                      session_inventory_verified=True,previous_sessions=[],inventory_sha256='2'*64),
                      model_executed=False,production_admitted=False)
        runtime=SimpleNamespace(registration=self.registration,role=self.role)
        @contextmanager
        def runtime_factory(*a,**k): yield runtime
        @contextmanager
        def network(*a,**k):
            self.events.append('open')
            try: yield 180
            finally: self.events.append('close')
        def inventory(*a,**k):
            self.assertFalse(self.active); self.events.append('inventory')
        def boundary(*a,**k): self.events.append('boundary-'+k['stage'])
        for name,value in [('ROOT',self.root),('SandboxRuntime',runtime_factory),('machine_probe_network',network),
                           ('inventory',inventory),('make_boundary_check',lambda pin:boundary),
                           ('require_managed_namespace',lambda:None),('check_network',lambda *a,**k:None),
                           ('_execute',self.execute)]:
            p=patch.object(flow,name,value); p.start(); self.addCleanup(p.stop)

    @contextmanager
    def role(self,name):
        self.roles+=1; number=self.roles; self.active=True; self.events.append('start'+str(number))
        repo=SimpleNamespace(log_dir=self.root/('b'*32 if number==1 else 'c'*32)/'logs')
        try: yield repo
        finally: self.active=False; self.events.append('stop'+str(number))

    def execute(self,repo,action,**kwargs):
        self.events.append(action)
        if self.fail==action: raise RuntimeError('synthetic failure')
        if action=='preflight': return self.pre
        if action=='dispatch':
            self.admission=kwargs['admission']
            return dict(returncode=0,timed_out=False,leader_reaped=True,process_group_stop_requested=True,
                        all_descendants_stopped=False,raw_output_suppressed=True,nonce='a'*32,
                        phase='awaiting_vm_stop',passed=False,production_admitted=False,resume_used=False)
        self.assertIn('stop1',self.events)
        result=dict(tool_call_count=1,attempt_nonce='a'*32,inspection_lease_id='c'*32,
                    expected_call_observed=True,discovery_verified=True,exact_model_verified=True,
                    linked_denial_observed=True,execution_marker_seen=False,production_admitted=False,
                    permission_denial_observed=True,passed=False,evidence_bound=True,
                    live_execution_verified=False,inspection_vm_stopped=False)
        for key in ('audit_sha256','export_sha256','session_sha256','launch_sha256','process_result_sha256'):
            result[key]='3'*64
        result['supervision_sha256']=flow.sha(self.admission)
        result['stop_receipt_sha256']=flow.sha(kwargs['stop_raw'])
        if self.fail=='hash': result['stop_receipt_sha256']='0'*64
        return result

    def test_ordered_lifecycle_remains_unaccepted(self):
        result=flow.run_probe(self.registration)
        self.assertTrue(result['all_vms_stopped']); self.assertFalse(result['passed'])
        self.assertFalse(result['permission_denial_accepted'])
        self.assertLess(self.events.index('close'),self.events.index('stop1'))
        self.assertLess(self.events.index('boundary-before_prepare'),self.events.index('preflight'))
        self.assertLess(self.events.index('stop1'),self.events.index('collect'))
        self.assertLess(self.events.index('collect'),self.events.index('stop2'))
        folder=Path(result['evidence'])
        self.assertEqual(flow.sha((folder/'admission.json').read_bytes()),result['collection']['supervision_sha256'])
        self.assertEqual(flow.sha((folder/'model-stop.json').read_bytes()),result['collection']['stop_receipt_sha256'])

    def test_dispatch_failure_closes_stops_and_never_collects(self):
        self.fail='dispatch'
        with self.assertRaises(RuntimeError): flow.run_probe(self.registration)
        self.assertIn('close',self.events); self.assertIn('stop1',self.events)
        self.assertNotIn('collect',self.events)

    def test_stale_registration_blocks_before_vm(self):
        (self.root/'sandbox-registry.json').write_text('{}')
        with self.assertRaises(ValueError): flow.run_probe(self.registration)
        self.assertNotIn('start1',self.events)

    def test_mismatched_evidence_still_stops_inspection(self):
        self.fail='hash'
        with self.assertRaises(ValueError): flow.run_probe(self.registration)
        self.assertIn('stop2',self.events)
        record=json.loads(next(self.root.glob('mcp-lifecycle-*/receipt.json')).read_bytes())
        self.assertFalse(record['all_vms_stopped'])
        self.assertFalse(record['passed'])


if __name__=='__main__': unittest.main()
