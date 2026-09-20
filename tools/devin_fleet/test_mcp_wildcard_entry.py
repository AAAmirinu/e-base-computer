from contextlib import nullcontext
import json
import unittest
from unittest.mock import patch
import mcp_wildcard_entry as entry
import inspect_auth_interface as inspection
from guest_mcp_prepare import WILDCARD_PROBE as prepare
from guest_mcp_inspect import WILDCARD_PROBE as inspect


class EntryTests(unittest.TestCase):
    def test_only_once_before_namespace_or_read(self):
        with patch.object(entry, 'require_managed_namespace') as guard:
            for args in ([], ['--resume'], ['--once','extra']):
                with self.assertRaises(ValueError): entry.main(args)
            guard.assert_not_called()

    def test_entry_preserves_cleanup_and_fixed_registration(self):
        with patch.object(entry,'require_managed_namespace') as guard, patch.object(
                entry,'interruption_cleanup',return_value=nullcontext()), patch.object(
                entry,'_file',return_value=b'{"production_enabled":false}') as read, patch.object(
                entry,'run_wildcard',return_value={'passed':False}) as run, patch('builtins.print'):
            entry.main(['--once'])
        guard.assert_called_once()
        read.assert_called_once_with(entry.ROOT/'sandbox-registry.json',1048576)
        run.assert_called_once_with({'production_enabled':False})

    def test_wildcard_mode_conflicts_refused_before_namespace(self):
        for kwargs in ({}, {'prepare_mcp':True,'inspect_mcp':True},
                {'prepare_mcp':True,'discovery':True}, {'prepare_mcp':True,'dispatch_preflight':True}):
            with patch.object(inspection,'require_managed_namespace') as guard:
                with self.assertRaises(ValueError): inspection.main(wildcard=True,**kwargs)
                guard.assert_not_called()

    def test_prepare_and_inspect_bootstraps_do_not_dispatch(self):
        for source in (prepare,inspect):
            compile(source,'<fixed-wildcard>','exec')
            self.assertNotIn('launch_reserved',source)
            self.assertNotIn('dispatch.dispatch',source)
        self.assertIn('module.WILDCARD_STATE',prepare)
        self.assertIn('module.inspect_wildcard',inspect)


if __name__ == '__main__': unittest.main()
