"""Pure recovery CLI routing and mocked wrapper tests; no live recovery."""
import io
import json
import signal
import unittest
from unittest.mock import patch

import recover_model_network as recovery
from launch_machine_auth import LOGIN_ROLES, model_recovery_command


class ModelNetworkRecoveryCliTests(unittest.TestCase):
    def setUp(self):
        self.registration={'production_enabled': True, 'synthetic': 'fixed registry'}
        self.guard=self.patch(recovery,'require_managed_namespace')
        self.read=self.patch(recovery,'_file',return_value=json.dumps(self.registration).encode())
        self.recover=self.patch(recovery,'recover',return_value={'phase': 'closed_recovery'})
        self.handlers={sig: object() for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP)}
        self.previous=dict(self.handlers)
        self.signals=self.patch(signal,'signal',side_effect=self.set_handler)
        self.output=io.StringIO()
        self.patch(recovery,'print',side_effect=lambda value,**kwargs:self.output.write(value),create=True)

    def patch(self,owner,name,*args,**kwargs):
        context=patch.object(owner,name,*args,**kwargs)
        result=context.start()
        self.addCleanup(context.stop)
        return result

    def set_handler(self,sig,handler):
        previous=self.handlers[sig]
        self.handlers[sig]=handler
        return previous

    def test_all_ten_roles_reach_exact_recover_using_fixed_registry(self):
        self.assertEqual(set(LOGIN_ROLES),set(recovery.ROLES))
        self.assertEqual(len(LOGIN_ROLES),10)
        for role in LOGIN_ROLES:
            with self.subTest(role=role):
                self.recover.reset_mock()
                recovery.main(['--role',role])
                self.recover.assert_called_once_with(self.registration,role)
                self.assertEqual(self.handlers,self.previous)
                self.read.assert_called_with(recovery.ROOT/'sandbox-registry.json',65536)
        self.assertEqual(self.guard.call_count,10)

    def test_bad_arguments_refused_before_namespace_files_or_handlers(self):
        invalid=([],['--role'],['--role','unknown'],['--role','../machine'],
                 ['--role','machine','extra'],['--role','machine','--id','abc'],
                 ['--role','machine','--root','/tmp'],['--role','/tmp/machine'],
                 ['--role','aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'],
                 ['--role','machine;anything'],('--role','machine'))
        for args in invalid:
            with self.subTest(args=args),self.assertRaises(ValueError):
                recovery.main(args)
        self.guard.assert_not_called()
        self.read.assert_not_called()
        self.recover.assert_not_called()
        self.signals.assert_not_called()

    def test_namespace_failure_has_no_registry_read_or_recovery(self):
        self.guard.side_effect=RuntimeError('synthetic namespace mismatch')
        with self.assertRaises(RuntimeError):
            recovery.main(['--role','machine'])
        self.read.assert_not_called()
        self.recover.assert_not_called()
        self.signals.assert_not_called()

    def test_success_restores_handlers_and_prints_only_result(self):
        recovery.main(['--role','machine'])
        self.assertEqual(self.handlers,self.previous)
        self.assertEqual(json.loads(self.output.getvalue()),{'phase':'closed_recovery'})
        self.assertEqual(self.signals.call_count,6)

    def test_recovery_exception_restores_handlers_without_printing_success(self):
        self.recover.side_effect=RuntimeError('synthetic recovery failure')
        with self.assertRaises(RuntimeError):
            recovery.main(['--role','machine'])
        self.assertEqual(self.handlers,self.previous)
        self.assertEqual(self.output.getvalue(),'')

    def test_installed_signal_interrupt_restores_handlers(self):
        def interrupt(*args,**kwargs):
            self.handlers[signal.SIGTERM](signal.SIGTERM,None)
        self.recover.side_effect=interrupt
        with self.assertRaises(KeyboardInterrupt):
            recovery.main(['--role','machine'])
        self.assertEqual(self.handlers,self.previous)
        self.assertEqual(self.output.getvalue(),'')

    def test_duplicate_registry_json_rejected_before_recovery(self):
        self.read.return_value=b'{"production_enabled":true,"production_enabled":false}'
        with self.assertRaises(ValueError):
            recovery.main(['--role','machine'])
        self.recover.assert_not_called()
        self.signals.assert_not_called()

    def test_launcher_maps_only_fixed_role_to_fixed_script(self):
        for role in LOGIN_ROLES:
            self.assertEqual(model_recovery_command(['--recover-model-network',role]),
                ['/home/fleet/controller-validation/recover_model_network.py','--role',role])
        for args in ([],['--catalog-check'],['--recover-role','machine']):
            self.assertIsNone(model_recovery_command(args))
        for args in (['--recover-model-network'],['--recover-model-network','unknown'],
                     ['--recover-model-network','../machine'],
                     ['--recover-model-network','machine','--id','abc'],
                     ['--recover-model-network','machine','--root','/tmp']):
            with self.subTest(args=args),self.assertRaises(RuntimeError):
                model_recovery_command(args)
        self.guard.assert_not_called()
        self.read.assert_not_called()
        self.recover.assert_not_called()


if __name__=='__main__':
    unittest.main()
