import unittest
from unittest.mock import patch
import guest_mcp_prepare as prep
import guest_mcp_inspect as inspect


class ControlStateTests(unittest.TestCase):
    def test_separate_fixed_state(self):
        self.assertEqual(prep.CONTROL_STATE,'/home/agent/.local/state/e-base-mcp-echo-control-v2')
        self.assertNotEqual(prep.CONTROL_STATE,prep.PREVIOUS_CONTROL_STATE)
        self.assertNotIn(prep.CONTROL_STATE,(prep.STATE,prep.DISCOVERY_STATE,prep.WILDCARD_STATE))

    def test_requires_explicit_builder(self):
        with patch.object(prep,'decode_sources') as decode:
            with self.assertRaises(ValueError):prep.prepare('unused',state_directory=prep.CONTROL_STATE)
            decode.assert_not_called()

    def test_previous_control_refused_before_decode(self):
        with patch.object(prep,'decode_sources') as decode:
            for source in (None,'trusted'):
                with self.assertRaises(ValueError):
                    prep.prepare('unused',state_directory=prep.PREVIOUS_CONTROL_STATE,discovery_source=source)
            decode.assert_not_called()

    def test_inspection_routes_only_fixed_state(self):
        with patch.object(inspect,'_inspect_profile') as check:
            inspect.inspect_control('bundle','source')
            check.assert_called_once_with('bundle','source',prep.CONTROL_STATE)


if __name__=='__main__':unittest.main()
