import copy
import hashlib
import json
import unittest
from mcp_probe_binding import ARTIFACTS, bind_probe
from test_mcp_denial_probe import export


class BindingTests(unittest.TestCase):
    def setUp(self):
        self.nonce='a'*32
        self.inputs={key:b'fixed synthetic input' for key in ARTIFACTS}
        self.audit=(self.nonce+':initialized\n'+self.nonce+':listed\n').encode()
        payload=export()
        payload['session_id']='new-synthetic-session'
        self.export=json.dumps(payload).encode()
        sha=lambda raw:hashlib.sha256(raw).hexdigest()
        self.reservation=dict(schema=1,nonce=self.nonce,phase='reserved',audit_identity=[1,2],
            previous_sessions=['old-session'],input_sha256={key:sha(raw) for key,raw in self.inputs.items()})
        self.completion=dict(nonce=self.nonce,returncode=0,processes_stopped=True,resume_used=False,
            audit_identity=[1,2],audit_sha256=sha(self.audit),export_sha256=sha(self.export))

    def bind(self,**updates):
        args=dict(inputs_before=self.inputs,inputs_after=self.inputs,audit_raw=self.audit,export_raw=self.export)
        args.update(updates)
        return bind_probe(self.reservation,self.completion,**args)

    def test_binds_without_claiming_live_execution(self):
        result=self.bind()
        self.assertTrue(result['evidence_bound'])
        self.assertTrue(result['permission_denial_observed'])
        self.assertFalse(result['passed'])
        self.assertFalse(result['live_execution_verified'])

    def test_input_swap_or_final_hash_change(self):
        changed=dict(self.inputs,**{'fixture.py':b'changed'})
        with self.assertRaises(ValueError): self.bind(inputs_after=changed)
        with self.assertRaises(ValueError): self.bind(audit_raw=self.audit+b'called\n')
        with self.assertRaises(ValueError): self.bind(export_raw=self.export+b' ')

    def test_still_running_resume_failure_or_wrong_inode(self):
        for key,value in (('processes_stopped',False),('resume_used',True),('returncode',1),
                          ('returncode',False),('audit_identity',[1,3]),('nonce','b'*32)):
            saved=copy.deepcopy(self.completion)
            self.completion[key]=value
            with self.assertRaises(ValueError): self.bind()
            self.completion=saved

    def test_previous_session_refused(self):
        self.reservation['previous_sessions'].append('new-synthetic-session')
        with self.assertRaises(ValueError): self.bind()

    def test_mixed_nonce_refused_even_with_updated_hash(self):
        mixed=self.audit+('b'*32+':listed\n').encode()
        self.completion['audit_sha256']=hashlib.sha256(mixed).hexdigest()
        with self.assertRaises(ValueError): self.bind(audit_raw=mixed)

    def test_actual_tool_call_disqualifies_denial(self):
        self.audit+=(self.nonce+':called\n').encode()
        self.completion['audit_sha256']=hashlib.sha256(self.audit).hexdigest()
        self.assertFalse(self.bind()['permission_denial_observed'])


if __name__=='__main__': unittest.main()
