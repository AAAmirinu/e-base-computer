import os
import unittest
from unittest.mock import patch

if os.name=='posix':
    import interactive_machine_auth as auth
    import launch_machine_auth as launcher

@unittest.skipUnless(os.name=='posix','Dedicated Linux controller')
class RoleSmokeTests(unittest.TestCase):
    def test_fixed_launcher_command(self):
        self.assertIsNone(launcher.role_model_smoke_command(['--inspect-policy']))
        self.assertEqual(launcher.role_model_smoke_command(['--model-smoke-role','coordinator']),
            ['/home/fleet/controller-validation/interactive_machine_auth.py','--model-smoke-role','coordinator'])
        for args in (['--model-smoke-role'],['--model-smoke-role','validation'],
                     ['--model-smoke-role','coordinator','extra'],['--model-smoke-role','../machine']):
            with self.assertRaises(RuntimeError):launcher.role_model_smoke_command(args)

    def test_selected_role_reaches_same_bounded_smoke(self):
        with patch.object(auth,'NAME',auth.NAME),patch.object(auth,'UUID',auth.UUID), \
             patch.object(auth,'main') as main:
            auth.select_login_target('coordinator')
            auth.main(model_smoke=True)
            main.assert_called_once_with(model_smoke=True)
            self.assertEqual(auth.NAME,'e-base-coordinator')

if __name__=='__main__':unittest.main()
