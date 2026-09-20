from contextlib import nullcontext
import unittest
from unittest.mock import patch
import registered_turn_entry as entry
import launch_machine_auth as launcher


class EntryTests(unittest.TestCase):
    def test_invalid_arguments_before_namespace(self):
        with patch.object(entry,'require_managed_namespace') as guard,patch.object(entry,'load') as load:
            for args in ([],['--once'],['--resume','a'*32],['--once','../x'],['--once','a'*32,'extra']):
                with self.assertRaises(ValueError):entry.main(args)
            guard.assert_not_called();load.assert_not_called()

    def test_single_fixed_invocation(self):
        with patch.object(entry,'require_managed_namespace'),patch.object(entry,'interruption_cleanup',return_value=nullcontext()),patch.object(entry,'load',return_value={'state':{}}) as load,patch.object(entry,'run') as run,patch('builtins.print') as output:
            entry.main(['--once','a'*32])
            load.assert_called_once_with('a'*32);run.assert_called_once_with(state={})
            self.assertIn('invocation_returned',output.call_args.args[0])

    def test_failure_never_retries_or_reports_completion(self):
        with patch.object(entry,'require_managed_namespace'),patch.object(entry,'interruption_cleanup',return_value=nullcontext()),patch.object(entry,'load',return_value={}),patch.object(entry,'run',side_effect=RuntimeError('held')) as run,patch('builtins.print') as output:
            with self.assertRaises(RuntimeError):entry.main(['--once','a'*32])
            self.assertEqual(run.call_count,1);output.assert_not_called()

    def test_launcher_fixed_route(self):
        self.assertIsNone(launcher.registered_turn_command(['--inspect-policy']))
        self.assertEqual(launcher.registered_turn_command(['--registered-turn-once','a'*32]),
            ['/home/fleet/controller-validation/registered_turn_entry.py','--once','a'*32])
        for args in (['--registered-turn-once'],['--registered-turn-once','../x'],['--registered-turn-once','a'*32,'extra']):
            with self.assertRaises(RuntimeError):launcher.registered_turn_command(args)


if __name__=='__main__':unittest.main()
