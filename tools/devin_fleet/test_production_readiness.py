from contextlib import nullcontext
import unittest
from unittest.mock import patch
import production_readiness as readiness

class Runtime:
    def __init__(self,registration,root,capacity):self.registration=registration
    def __enter__(self):return self
    def __exit__(self,*args):return False

class ReadinessTests(unittest.TestCase):
    def test_all_roles_checked_but_not_accepted(self):
        roles={r:{'image_digest':'sha256:'+'a'*64} for r in readiness.ROLES}
        candidate={'controller_root':'/root','roles':roles}
        raw=b'candidate'
        with patch.object(readiness,'require_managed_namespace'), \
             patch.object(readiness,'inspect',side_effect=[{'candidate_sha256':'b'*64,'migration_epoch':'epoch'},{'candidate_sha256':'b'*64,'migration_epoch':'epoch'}]), \
             patch.object(readiness,'_file',side_effect=[raw,raw]), \
             patch.object(readiness.json,'loads',return_value=candidate), \
             patch.object(readiness,'SandboxRuntime',Runtime), \
             patch.object(readiness,'check_network') as network, \
             patch.object(readiness,'check_host_boundary') as boundary, \
             patch.object(readiness,'inspect_role_authentication',
                          return_value={'verified':True,'role_count':10}) as authentication, \
             patch.object(readiness,'inspect_normal_permission',
                          return_value={'verified':True,'permission_mode':'normal'}) as normal:
            with patch.object(readiness,'inspect_physical_reboot', return_value={
                    'verified':True,'candidate_sha256':'b'*64,'all_vms_stopped':True,
                    'automatic_resume':False,'activated':False,'published':False}), \
                 patch.object(readiness,'inspect_full_turn', return_value={
                    'verified':True,'candidate_sha256':'b'*64,
                    'migration_epoch':'epoch','activated':False,'published':False}):
                result=readiness.check()
        self.assertEqual(network.call_count,10);self.assertEqual(boundary.call_count,10)
        authentication.assert_called_once()
        normal.assert_called_once()
        self.assertTrue(result['activation_ready']);self.assertFalse(result['activated'])
        self.assertTrue(result['all_vms_stopped']);self.assertEqual(result['blockers'],[])
        self.assertTrue(result['role_authentication']['verified'])

    def test_full_turn_drift_is_rejected(self):
        roles={r:{'image_digest':'sha256:'+'a'*64} for r in readiness.ROLES}
        candidate={'controller_root':'/root','roles':roles}
        base={'verified':True,'candidate_sha256':'b'*64,'migration_epoch':'epoch',
              'activated':False,'published':False}
        changed=dict(base, operation_id='changed')
        with patch.object(readiness,'require_managed_namespace'), \
             patch.object(readiness,'inspect',side_effect=[{'candidate_sha256':'b'*64,'migration_epoch':'epoch'},{'candidate_sha256':'b'*64,'migration_epoch':'epoch'}]), \
             patch.object(readiness,'_file',side_effect=[b'candidate',b'candidate']), \
             patch.object(readiness.json,'loads',return_value=candidate), \
             patch.object(readiness,'SandboxRuntime',Runtime), \
             patch.object(readiness,'check_network'), \
             patch.object(readiness,'check_host_boundary'), \
             patch.object(readiness,'inspect_role_authentication',return_value={'verified':True}), \
             patch.object(readiness,'inspect_normal_permission',return_value={'verified':True}), \
             patch.object(readiness,'inspect_physical_reboot',return_value={
                 'verified':True,'candidate_sha256':'b'*64,'all_vms_stopped':True,
                 'automatic_resume':False,'activated':False,'published':False}), \
             patch.object(readiness,'inspect_full_turn',side_effect=[base,changed]):
            with self.assertRaisesRegex(ValueError,'Exact non-activating'):
                readiness.check()

    def test_failure_stops_without_acceptance(self):
        roles={r:{'image_digest':'sha256:'+'a'*64} for r in readiness.ROLES}
        with patch.object(readiness,'require_managed_namespace'),patch.object(readiness,'inspect',return_value={'candidate_sha256':'b'*64}),patch.object(readiness,'_file',return_value=b'x'),patch.object(readiness.json,'loads',return_value={'controller_root':'/root','roles':roles}),patch.object(readiness,'SandboxRuntime',Runtime),patch.object(readiness,'check_network',side_effect=ValueError('open')),patch.object(readiness,'inspect_role_authentication'),patch.object(readiness,'inspect_normal_permission'),patch.object(readiness,'inspect_full_turn',return_value={'verified':True}):
            with self.assertRaisesRegex(ValueError,'open'):readiness.check()

if __name__=='__main__':unittest.main()
