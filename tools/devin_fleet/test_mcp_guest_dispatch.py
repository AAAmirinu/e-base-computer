import base64
import hashlib
import json
from pathlib import Path
import time
import unittest
from unittest.mock import patch
import zlib
import guest_mcp_dispatch as guest
from mcp_probe_supervision import MACHINE


class DispatchTests(unittest.TestCase):
    def setUp(self):
        p=patch.object(guest,'verify_cli'); p.start(); self.addCleanup(p.stop)
        self.raw=b'{"nonce":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}'
        self.binding=dict(nonce='a'*32,work='/tmp/e-base-mcp-probe-12345678',
                          reservation_sha256=hashlib.sha256(self.raw).hexdigest())
        now=int(time.time())
        self.receipt=dict(self.binding,schema=2,machine_vm_id=MACHINE,lease_id='b'*32,
                          issued_at=now,expires_at=now+120,session_inventory_scope='current_workdir',
                          session_inventory_verified=True,fresh_attempt_preconditions_verified=True,previous_sessions=[])
        p=patch.object(guest,'read_binding',return_value=(self.binding,self.raw)); p.start(); self.addCleanup(p.stop)

    def test_support_bundle_exact_roundtrip(self):
        encoded=guest.encode_support(Path(__file__).parent)
        sources=guest.decode_support(encoded)
        self.assertEqual(set(sources),set(guest.SUPPORT))
        payload=json.loads(zlib.decompress(base64.b64decode(encoded)))
        payload['mcp_probe_launch']['sha256']='0'*64
        with self.assertRaises(ValueError): guest.decode_support(base64.b64encode(zlib.compress(json.dumps(payload).encode())).decode())
        compile(guest.PROBE,'trusted-probe','exec')

    def test_dispatch_uses_bound_callback_and_actual_inventory(self):
        raw=json.dumps(self.receipt).encode()
        def launch(state,*,supervised_check):
            self.assertEqual(supervised_check(**self.binding,timeout=30),raw)
            return {'passed':False}
        with patch.object(guest,'launch_reserved',side_effect=launch),patch.object(
                guest,'read_empty_workdir_inventory',return_value=dict(work=self.binding['work'],previous_sessions=[])) as inventory:
            self.assertFalse(guest.dispatch(raw)['passed'])
        self.assertEqual(inventory.call_args.args,(self.binding['work'],))
        self.assertLessEqual(inventory.call_args.kwargs['timeout'],10)

    def test_expired_or_foreign_admission_never_launches(self):
        for change in ({'nonce':'c'*32},{'expires_at':self.receipt['issued_at']-1},{'work':'/tmp/e-base-mcp-probe-87654321'}):
            with self.subTest(change=change),patch.object(guest,'launch_reserved') as launch:
                with self.assertRaises(ValueError): guest.dispatch(json.dumps(dict(self.receipt,**change)).encode())
                launch.assert_not_called()

    def test_inventory_failure_is_not_empty(self):
        def launch(state,*,supervised_check): return supervised_check(**self.binding,timeout=30)
        with patch.object(guest,'launch_reserved',side_effect=launch),patch.object(
                guest,'read_empty_workdir_inventory',side_effect=ValueError('inventory failed')):
            with self.assertRaisesRegex(ValueError,'inventory failed'):
                guest.dispatch(json.dumps(self.receipt).encode())

    def test_preflight_does_not_launch(self):
        with patch.object(guest,'snapshot',return_value={'inputs':{}}),patch.object(guest,'check_inherited'),patch.object(
                guest,'check_main_config',return_value='same'),patch.object(guest,'read_empty_workdir_inventory',
                return_value=dict(work=self.binding['work'],previous_sessions=[])),patch.object(guest,'launch_reserved') as launch:
            self.assertFalse(guest.preflight()['model_executed'])
            launch.assert_not_called()


if __name__=='__main__': unittest.main()
