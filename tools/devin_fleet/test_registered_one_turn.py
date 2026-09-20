import hashlib
import unittest
from unittest.mock import patch
import registered_one_turn as driver


class DriverTests(unittest.TestCase):
    def args(self):
        return dict(registration={'production_enabled':True},controller_root='/root',
            project_root='/project',role='machine',entry={},state={},settings={},
            cycle_directory='/root/cycle',sequence=0,parent_bundle=b'bundle',
            parent_bundle_sha256=hashlib.sha256(b'bundle').hexdigest(),parent_ref='refs/heads/main')

    def test_fixed_adapters_and_parent_binding(self):
        args=self.args()
        with patch.object(driver,'require_managed_namespace'),patch.object(driver,'run_registered_one_turn',return_value={'phase':'pending_review'}) as turn:
            result=driver.run(**args)
        self.assertEqual(result,{'phase':'pending_review'})
        bound=turn.call_args.kwargs
        self.assertIs(bound['validate'],driver.validate)
        self.assertIs(bound['runtime_factory'].func,driver.SandboxRuntime)
        self.assertEqual(bound['runtime_factory'].keywords,{'capacity':1})
        self.assertIs(bound['build_and_import'].func,driver.build_and_import)
        self.assertEqual(bound['build_and_import'].keywords['parent_bundle'],b'bundle')
        args['registration']['production_enabled']=False
        self.assertTrue(bound['registration']['production_enabled'])

    def test_invalid_inputs_never_enter_pipeline(self):
        for change in ({'registration':{'production_enabled':False}},
                       {'parent_bundle':b''},{'parent_bundle_sha256':'0'*64},
                       {'parent_ref':'main'}):
            with patch.object(driver,'require_managed_namespace'),patch.object(driver,'run_registered_one_turn') as turn:
                with self.assertRaises(ValueError):driver.run(**dict(self.args(),**change))
                turn.assert_not_called()

    def test_failure_is_not_retried(self):
        with patch.object(driver,'require_managed_namespace'),patch.object(driver,'run_registered_one_turn',side_effect=RuntimeError('held')) as turn:
            with self.assertRaisesRegex(RuntimeError,'held'):driver.run(**self.args())
            self.assertEqual(turn.call_count,1)


if __name__=='__main__':unittest.main()
