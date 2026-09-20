import json
import unittest
import production_normal_permission as normal

class NormalPermissionTests(unittest.TestCase):
    def setUp(self):
        self.candidate={'roles':{'machine':{'id':'vm','name':'e-base-machine',
            'image_digest':'sha256:'+'a'*64}}}

    def outer(self,extra,executed):
        return {'schema':1,'phase':'closed','sandbox_id':'vm','sandbox_name':'e-base-machine',
            'auth_hosts':normal.HOSTS,'original_deny_id':'deny','model_executed':executed,
            'terminal_recorded':False,'network_denied_after':True,'all_vms_stopped':True,
            'cleanup_errors':[],**extra}

    def test_execution_requires_exact_success(self):
        smoke={'exact_model_verified':True,'file_write_verified':True,
            'model_executed':'attempted','no_tool_calls':False,'passed':True,
            'phase':'finished','production_admitted':False,'raw_output_suppressed':True,
            'response_marker_seen':True,'returncode':0,'shell_denial_verified':False}
        raw=json.dumps(self.outer({'temporary_deny_ids':[],'smoke':smoke},'attempted')).encode()
        self.assertEqual(normal._execution(raw,self.candidate),'normal_write_execution')
        smoke['file_write_verified']=False
        with self.assertRaisesRegex(ValueError,'execution'):
            normal._execution(json.dumps(self.outer(
                {'temporary_deny_ids':[],'smoke':smoke},'attempted')).encode(),self.candidate)

    def test_inspection_requires_one_expected_write(self):
        row={'all_calls_expected_write':True,'exact_model_verified':True,
            'expected_write_call_count':1,'export_sha256':'a'*64,'file_write_verified':True,
            'production_admitted':False,'shell_denial_verified':False,'tool_call_count':1}
        wrapper={'file_probe_evidence':[row],'model_executed':False,'raw_output_suppressed':True}
        raw=json.dumps(self.outer({'smoke_evidence':wrapper},False)).encode()
        self.assertEqual(normal._inspection(raw,self.candidate),'normal_write_inspection')
        row['tool_call_count']=2
        with self.assertRaisesRegex(ValueError,'inspection'):
            normal._inspection(json.dumps(self.outer({'smoke_evidence':wrapper},False)).encode(),
                               self.candidate)

if __name__=='__main__':unittest.main()
