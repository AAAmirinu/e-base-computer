import unittest
from unittest.mock import patch
import guest_mcp_prepare as preparation
import guest_mcp_inspect as inspection


class WildcardStateTests(unittest.TestCase):
    def test_state_is_fixed_and_separate(self):
        self.assertEqual(preparation.WILDCARD_STATE,
                         '/home/agent/.local/state/e-base-mcp-wildcard-v1')
        self.assertEqual(len({preparation.STATE, preparation.DISCOVERY_STATE,
                              preparation.WILDCARD_STATE}), 3)

    def test_profile_requires_explicit_source_before_decode_or_mutation(self):
        for state in (preparation.DISCOVERY_STATE, preparation.WILDCARD_STATE):
            with patch.object(preparation, 'decode_sources') as decode:
                with self.assertRaises(ValueError): preparation.prepare('unused', state_directory=state)
                decode.assert_not_called()

    def test_wildcard_source_reaches_bundle_validation_only(self):
        with patch.object(preparation, 'decode_sources', side_effect=ValueError('bundle sentinel')):
            with self.assertRaisesRegex(ValueError, 'bundle sentinel'):
                preparation.prepare('unused', state_directory=preparation.WILDCARD_STATE,
                                    discovery_source='# trusted source')

    def test_named_wrappers_route_exact_state(self):
        with patch.object(inspection, '_inspect_profile', return_value={'sentinel': True}) as inspect:
            inspection.inspect_wildcard('bundle', 'source')
            inspect.assert_called_once_with('bundle', 'source', preparation.WILDCARD_STATE)
        with patch.object(inspection, '_inspect_profile') as inspect:
            inspection.inspect_discovery('bundle', 'source')
            inspect.assert_called_once_with('bundle', 'source', preparation.DISCOVERY_STATE)

    def test_unknown_state_and_unbounded_source_rejected_before_inspection(self):
        with patch.object(inspection, 'inspect_prepared') as inspect:
            with self.assertRaises(ValueError): inspection._inspect_profile('bundle', 'source', '/tmp/other')
            for source in ('', 'x'*16385, None):
                with self.assertRaises(ValueError): inspection.inspect_wildcard('bundle', source)
            inspect.assert_not_called()


if __name__ == '__main__': unittest.main()
