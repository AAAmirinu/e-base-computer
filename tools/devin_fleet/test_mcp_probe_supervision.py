import hashlib
import json
import unittest
from mcp_probe_supervision import MACHINE,validate_receipt,bind_supervised_probe
import test_mcp_probe_binding as fixtures


class SupervisionTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.BindingTests()
        self.fixture.setUp()
        self.reservation=json.dumps(self.fixture.reservation).encode()
        self.value=dict(schema=2,nonce=self.fixture.nonce,reservation_sha256=hashlib.sha256(self.reservation).hexdigest(),
                        work='/tmp/e-base-mcp-probe-12345678',machine_vm_id=MACHINE,lease_id='b'*32,
                        issued_at=100,expires_at=200,session_inventory_scope='current_workdir',
                        session_inventory_verified=True,fresh_attempt_preconditions_verified=True,
                        previous_sessions=['old-session'])

    def test_rejects_identity_time_and_history_changes(self):
        for key,value in [('schema',True),('nonce','c'*32),('reservation_sha256','0'*64),
                          ('machine_vm_id','different'),('lease_id','bad'),('work','/tmp/other'),
                          ('issued_at',True),('expires_at',281),('session_inventory_verified',False),
                          ('schema',1),('session_inventory_scope','account'),('fresh_attempt_preconditions_verified',False),
                          ('previous_sessions',['duplicate','duplicate']),('previous_sessions',['control\n'])]:
            with self.subTest(key=key),self.assertRaises(ValueError):
                validate_receipt(json.dumps(dict(self.value,**{key:value})).encode(),
                                 nonce=self.fixture.nonce,reservation_raw=self.reservation,now=150)

    def test_bounded_extended_receipt_and_expiry(self):
        raw=json.dumps(dict(self.value,expires_at=280)).encode()
        validate_receipt(raw,nonce=self.fixture.nonce,reservation_raw=self.reservation,now=279)
        with self.assertRaises(ValueError):
            validate_receipt(raw,nonce=self.fixture.nonce,reservation_raw=self.reservation,now=280)

    def bind(self):
        f=self.fixture
        return bind_supervised_probe(self.reservation,json.dumps(self.value).encode(),f.completion,
                                    inputs_before=f.inputs,inputs_after=f.inputs,audit_raw=f.audit,export_raw=f.export)

    def test_admission_history_is_used_without_mutating_reservation(self):
        self.assertFalse(self.bind()['passed'])
        self.value['previous_sessions']=['old-session','new-synthetic-session']
        with self.assertRaises(ValueError): self.bind()
        self.assertEqual(json.loads(self.reservation)['previous_sessions'],['old-session'])

    def test_known_history_cannot_be_dropped(self):
        self.value['previous_sessions']=[]
        with self.assertRaises(ValueError): self.bind()


if __name__=='__main__': unittest.main()
