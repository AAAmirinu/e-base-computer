from contextlib import nullcontext
import unittest
from unittest.mock import patch
import mcp_echo_control_entry as entry
import inspect_auth_interface as inspection


class EntryTests(unittest.TestCase):
    def test_only_once_before_namespace(self):
        with patch.object(entry,'require_managed_namespace') as guard:
            for args in ([],['--resume'],['--once','extra']):
                with self.assertRaises(ValueError):entry.main(args)
            guard.assert_not_called()

    def test_fixed_registration_and_cleanup(self):
        with patch.object(entry,'require_managed_namespace'),patch.object(entry,'interruption_cleanup',return_value=nullcontext()),patch.object(entry,'_file',return_value=b'{"production_enabled":false}') as read,patch.object(entry,'run_control',return_value={'passed':False}) as run,patch('builtins.print'):
            entry.main(['--once'])
        read.assert_called_once_with(entry.ROOT/'sandbox-registry.json',1048576)
        run.assert_called_once_with({'production_enabled':False})

    def test_prepare_conflicts_refused(self):
        cases=[{},dict(prepare_mcp=True,inspect_mcp=True)]
        cases += [dict(prepare_mcp=True,**{key:True}) for key in ('discovery','wildcard','cli_policy','dispatch_preflight','cli_link','history_shape')]
        for args in cases:
            with patch.object(inspection,'require_managed_namespace') as guard:
                with self.assertRaises(ValueError):inspection.main(control=True,**args)
                guard.assert_not_called()


if __name__=='__main__':unittest.main()
