import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import production_role_authentication as auth


class RoleAuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.candidate={'migration_epoch':'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
            'roles':{role:{'id':f'id-{role}','name':'e-base-'+role,
                           'image_digest':'sha256:'+'a'*64} for role in auth.ROLES}}

    def tearDown(self):self.temp.cleanup()

    def receipt(self,role):
        entry=self.candidate['roles'][role]
        value={'schema':1,'phase':'closed','sandbox_id':entry['id'],
            'sandbox_name':entry['name'],'auth_hosts':auth.HOSTS,'original_deny_id':'deny',
            'model_executed':'attempted','terminal_recorded':False,'temporary_deny_ids':[],
            'smoke':{'model_executed':'attempted','raw_output_suppressed':True,
                'phase':'finished','returncode':0,'response_marker_seen':True,
                'exact_model_verified':True,'no_tool_calls':True,'passed':True},
            'network_denied_after':True,'all_vms_stopped':True,'cleanup_errors':[]}
        return (json.dumps(value)+'\n').encode()

    def make_manifest(self):
        roles={}
        for role in auth.ROLES:
            directory=self.root/('interactive-auth-'+role);directory.mkdir(mode=0o700)
            raw=self.receipt(role);(directory/'receipt.json').write_bytes(raw)
            entry=self.candidate['roles'][role]
            roles[role]={'sandbox_id':entry['id'],'sandbox_name':entry['name'],
                'image_digest':entry['image_digest'],'evidence_kind':'fixed_smoke_receipt',
                'receipt_path':str(directory/'receipt.json'),
                'receipt_sha256':hashlib.sha256(raw).hexdigest()}
        value={'schema':1,'phase':'complete','candidate_sha256':'b'*64,
            'migration_epoch':self.candidate['migration_epoch'],'role_count':10,'roles':roles,
            'credentials_copied':False,'raw_output_exported':False,'model_executed':False,
            'automatic_resume':False,'activated':False}
        evidence=self.root/'evidence';evidence.mkdir(mode=0o700)
        (evidence/'manifest.json').write_text(json.dumps(value))
        return evidence

    def test_inspect_binds_every_receipt(self):
        evidence=self.make_manifest()
        with patch.object(auth,'ROOT',self.root),patch.object(auth,'EVIDENCE',evidence), \
             patch.object(auth,'MANIFEST',evidence/'manifest.json'), \
             patch.object(auth,'require_managed_namespace'), \
             patch.object(auth,'_candidate',return_value=(
                 {'candidate_sha256':'b'*64},self.candidate)):
            result=auth.inspect(self.candidate,'b'*64)
        self.assertTrue(result['verified']);self.assertEqual(result['role_count'],10)

    def test_changed_receipt_is_rejected(self):
        evidence=self.make_manifest()
        path=self.root/'interactive-auth-machine'/'receipt.json'
        path.write_bytes(self.receipt('coordinator'))
        with patch.object(auth,'ROOT',self.root),patch.object(auth,'EVIDENCE',evidence), \
             patch.object(auth,'MANIFEST',evidence/'manifest.json'), \
             patch.object(auth,'require_managed_namespace'), \
             patch.object(auth,'_candidate',return_value=(
                 {'candidate_sha256':'b'*64},self.candidate)):
            with self.assertRaisesRegex(ValueError,'changed'):
                auth.inspect(self.candidate,'b'*64)

    def test_failed_smoke_is_rejected(self):
        raw=json.loads(self.receipt('machine'));raw['smoke']['passed']=False
        with self.assertRaisesRegex(ValueError,'success'):
            auth._successful_receipt(json.dumps(raw).encode(),self.candidate)

    def test_wrong_candidate_identity_is_rejected(self):
        raw=json.loads(self.receipt('machine'));raw['sandbox_id']='other'
        with self.assertRaisesRegex(ValueError,'candidate role'):
            auth._successful_receipt(json.dumps(raw).encode(),self.candidate)

    def test_legacy_export_is_machine_only(self):
        entry=self.candidate['roles']['machine']
        value={'schema':1,'phase':'closed','sandbox_id':entry['id'],
            'sandbox_name':entry['name'],'auth_hosts':auth.HOSTS,
            'original_deny_id':'deny','model_executed':False,'terminal_recorded':False,
            'smoke_evidence':{'smoke_export_metadata':[{'agent_model_names':['SWE-2 High'],
                'agent_steps':1,'export_sha256':'a'*64,'exact_model_verified':True,
                'no_tool_calls':True}]},'network_denied_after':True,
            'all_vms_stopped':True,'cleanup_errors':[]}
        self.assertEqual(auth._legacy_machine_receipt(
            json.dumps(value).encode(),self.candidate),
            ('machine','legacy_export_attestation'))
        value['sandbox_name']='e-base-coordinator'
        with self.assertRaisesRegex(ValueError,'outer'):
            auth._legacy_machine_receipt(json.dumps(value).encode(),self.candidate)


if __name__=='__main__':unittest.main()
