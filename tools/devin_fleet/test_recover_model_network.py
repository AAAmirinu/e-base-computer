"""Temporary-file recovery contracts; no real locks, VM, or network operations."""
from contextlib import nullcontext
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import uuid

import recover_model_network as recovery
from network_restart_guard import inspect_windows
from network_recovery_record import expected_record


class RecoverModelNetworkTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base=Path(temporary.name).resolve()
        self.root=self.base/'controller'
        self.root.mkdir(mode=0o700)
        self.run=self.root/'turn'
        self.run.mkdir(mode=0o700)
        self.window=self.run/'network-window'
        self.window.mkdir(mode=0o700)
        self.window_path=self.window/'network-window.json'
        self.window_path.write_bytes(b'{"phase":"opening"}')
        self.stop=self.root/'STOP'
        self.stop.write_bytes(b'hold')
        self.registration=dict(schema=1,production_enabled=True,controller_root=str(self.root),
            simultaneous_capacity_verified=1,migration_epoch='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
            roles={role:dict(name='e-base-'+role,id=str(uuid.UUID(int=i+1)))
                   for i,role in enumerate(sorted(recovery.ROLES))})
        self.registry=self.base/'sandbox-registry.json'
        self.write(self.registry,self.registration)
        fences=self.root/'model-turn-fences'
        fences.mkdir(mode=0o700)
        self.fence=fences/'machine.json'
        self.write(self.fence,dict(schema=1,role='machine',sequence=0,operation_id='b'*32,
            migration_epoch=self.registration['migration_epoch'],sandbox_id=self.registration['roles']['machine']['id'],
            state='unresolved',automatic_resume=False,run_directory=str(self.run)))
        self.original=(self.registry.read_bytes(),self.fence.read_bytes(),self.window_path.read_bytes(),self.stop.read_bytes())
        self.rows=[dict(entry,status='stopped') for entry in self.registration['roles'].values()]
        self.rows.append(dict(name='e-base-validation',id=recovery.VALIDATOR_ID,status='stopped'))
        self.transport=SimpleNamespace(control=Mock(side_effect=self.command))
        self.patch(recovery,'ROOT',self.base)
        self.patch(recovery,'require_managed_namespace')
        self.lock=self.patch(recovery,'GlobalLock',return_value=nullcontext())
        self.enter=self.patch(recovery.SandboxRuntime,'__enter__',side_effect=AssertionError('Runtime entry forbidden'))
        self.check=self.patch(recovery,'check_network',return_value=None)

    def patch(self,owner,name,*args,**kwargs):
        context=patch.object(owner,name,*args,**kwargs)
        result=context.start()
        self.addCleanup(context.stop)
        return result

    def write(self,path,value):
        path.write_text(json.dumps(value))
        path.chmod(0o600)

    def command(self,argv,timeout):
        if argv==['/usr/bin/sbx','ls','--json']:
            return SimpleNamespace(returncode=0,stdout=json.dumps({'sandboxes':self.rows}))
        self.assertEqual(argv,['/usr/bin/sbx','policy','deny','network','--sandbox','e-base-machine','**'])
        self.assertTrue((self.window/'recovery/recovery.json').is_file())
        return SimpleNamespace(returncode=0,stdout='{}')

    def invoke(self):
        return recovery.recover(self.registration,'machine',transport=self.transport)

    def saved(self):
        return json.loads((self.window/'recovery/recovery.json').read_bytes())

    def test_success_only_adds_deny_and_preserves_original_evidence(self):
        expected=expected_record(self.original[1],self.original[2],self.registration,'machine')
        self.assertEqual(self.invoke(),expected)
        self.assertEqual(self.saved(),expected)
        self.assertEqual((self.registry.read_bytes(),self.fence.read_bytes(),self.window_path.read_bytes(),self.stop.read_bytes()),self.original)
        self.assertEqual(self.transport.control.call_count,3)
        self.enter.assert_not_called()
        self.lock.assert_called_once_with('/tmp/e-base-devin-fleet-global.lock')
        self.assertEqual(inspect_windows(self.root,self.registration),{'machine':'recovered_closed'})

    def test_existing_recovery_directory_refuses_resend(self):
        self.invoke()
        with self.assertRaises(FileExistsError):
            self.invoke()
        self.assertEqual(self.transport.control.call_count,3)

    def test_running_vm_refused_before_policy_change(self):
        self.rows[0]['status']='running'
        with self.assertRaises(ValueError):
            self.invoke()
        self.assertEqual(self.transport.control.call_count,1)
        self.assertEqual(self.saved()['phase'],'inspection_required')

    def test_replaced_validator_refused(self):
        self.rows[-1]['id']=str(uuid.UUID(int=99))
        with self.assertRaises(ValueError):
            self.invoke()
        self.assertEqual(self.transport.control.call_count,1)

    def test_unknown_vm_with_missing_id_cannot_replace_registered_vm(self):
        self.rows[-1]=dict(name='unknown-vm',status='stopped')
        with self.assertRaises(ValueError):
            self.invoke()
        self.assertEqual(self.transport.control.call_count,1)

    def test_uncertain_deny_failure_does_not_retry_or_change_original_files(self):
        original=self.command
        def uncertain(argv,timeout):
            if 'deny' in argv:
                raise TimeoutError('synthetic policy timeout')
            return original(argv,timeout)
        self.transport.control.side_effect=uncertain
        with self.assertRaises(TimeoutError):
            self.invoke()
        self.assertEqual(self.transport.control.call_count,2)
        self.assertEqual(self.saved()['phase'],'inspection_required')
        self.assertEqual(self.fence.read_bytes(),self.original[1])
        self.assertEqual(self.window_path.read_bytes(),self.original[2])

    def test_network_verification_failure_retains_exclusive_hold(self):
        self.check.side_effect=RuntimeError('SYNTHETIC_PRIVATE_ERROR')
        with self.assertRaises(RuntimeError):
            self.invoke()
        self.assertEqual(self.saved()['phase'],'inspection_required')
        self.assertNotIn('SYNTHETIC_PRIVATE_ERROR',json.dumps(self.saved()))
        with self.assertRaises(FileExistsError):
            self.invoke()

    def test_non_none_network_verifier_result_rejected(self):
        self.check.return_value=False
        with self.assertRaises(ValueError):
            self.invoke()
        self.assertEqual(self.saved()['phase'],'inspection_required')

    def test_original_window_mutation_rejects_final_receipt(self):
        self.check.side_effect=lambda *args,**kwargs:self.window_path.write_bytes(b'changed') and None
        with self.assertRaises(ValueError):
            self.invoke()
        self.assertEqual(self.saved()['phase'],'inspection_required')

    def test_missing_window_receipt_refused_before_transport(self):
        self.window_path.unlink()
        with self.assertRaises(FileNotFoundError):
            self.invoke()
        self.assertFalse(self.window_path.exists())
        self.transport.control.assert_not_called()
        self.assertFalse((self.window/'recovery').exists())

    def test_existing_partial_window_preserved_and_bound(self):
        self.window_path.write_bytes(b'{')
        result=self.invoke()
        self.assertEqual(result,expected_record(self.original[1],b'{',self.registration,'machine'))
        self.assertEqual(self.window_path.read_bytes(),b'{')

    def test_registry_mismatch_prevents_reservation_and_transport(self):
        self.write(self.registry,dict(self.registration,production_enabled=False))
        with self.assertRaises(ValueError):
            self.invoke()
        self.assertFalse((self.window/'recovery').exists())
        self.transport.control.assert_not_called()


if __name__=='__main__':
    unittest.main()
