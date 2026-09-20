import os
import unittest

if os.name=='posix':import launch_machine_auth as launcher

@unittest.skipUnless(os.name=='posix','Dedicated Linux controller')
class RoleInventoryTests(unittest.TestCase):
    def test_fixed_role_command(self):
        self.assertIsNone(launcher.role_auth_inventory_command(['--auth-inventory']))
        self.assertEqual(launcher.role_auth_inventory_command(['--auth-inventory-role','toolchain']),
            ['/home/fleet/controller-validation/sandbox_auth_inventory.py','--role','toolchain'])
        for args in (['--auth-inventory-role'],['--auth-inventory-role','validation'],
                     ['--auth-inventory-role','../machine'],['--auth-inventory-role','machine','extra']):
            with self.assertRaises(RuntimeError):launcher.role_auth_inventory_command(args)

if __name__=='__main__':unittest.main()
