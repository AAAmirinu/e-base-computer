from pathlib import Path
import unittest
from unittest.mock import patch
import guest_mcp_prepare as prepare
import guest_mcp_inspect as inspect
import guest_mcp_wildcard as bootstrap
from mcp_compatible_control_source import compose

class CompatibleStateTests(unittest.TestCase):
    def test_fixed_state_distinct_and_builder_required(self):
        self.assertEqual(prepare.COMPATIBLE_CONTROL_STATE,'/home/agent/.local/state/e-base-mcp-echo-compatible-v1')
        self.assertNotEqual(prepare.COMPATIBLE_CONTROL_STATE,prepare.CONTROL_STATE)
        with patch.object(prepare,'decode_sources') as decode:
            with self.assertRaises(ValueError):prepare.prepare('unused',state_directory=prepare.COMPATIBLE_CONTROL_STATE)
            decode.assert_not_called()

    def test_inspection_uses_new_fixed_state(self):
        with patch.object(inspect,'_inspect_profile') as check:
            inspect.inspect_compatible_control('bundle','source')
            check.assert_called_once_with('bundle','source',prepare.COMPATIBLE_CONTROL_STATE)

    def test_actual_composed_bootstrap_state_and_collection(self):
        root=Path(__file__).parent
        read=lambda name:(root/name).read_text()
        builder=compose(read('mcp_echo_control_inputs.py'),read('mcp_fixture_compat.py'))
        args=(builder,read('mcp_echo_control_evidence.py'),read('mcp_discovery_evidence.py'),
              read('mcp_result_summary.py'),read('mcp_wildcard_denial_evidence.py'))
        code=bootstrap.make_compatible_control_probe(*args)
        compile(code,'<compatible-bootstrap>','exec')
        self.assertIn('prepare.STATE=prepare.COMPATIBLE_CONTROL_STATE',code)
        self.assertIn('inspect.inspect_compatible_control',code)
        self.assertIn('state_directory=prepare.COMPATIBLE_CONTROL_STATE',code)
        old=bootstrap.make_control_probe(*args)
        self.assertIn('prepare.STATE=prepare.CONTROL_STATE',old)
        self.assertNotIn('prepare.STATE=prepare.COMPATIBLE_CONTROL_STATE',old)

if __name__=='__main__':unittest.main()
