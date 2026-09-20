from pathlib import Path
import unittest
from unittest.mock import patch
import guest_mcp_prepare as prepare
import guest_mcp_inspect as inspect
import guest_mcp_wildcard as bootstrap
from mcp_params_control_source import compose


class ParamsStateTests(unittest.TestCase):
    def test_distinct_state_and_builder_required_before_decode(self):
        self.assertEqual(prepare.PARAMS_CONTROL_STATE, '/home/agent/.local/state/e-base-mcp-echo-params-v1')
        previous = [v for k, v in vars(prepare).items() if k.endswith('STATE') and k != 'PARAMS_CONTROL_STATE']
        self.assertNotIn(prepare.PARAMS_CONTROL_STATE, previous)
        for source in (None, '', 'x'*16385, 1):
            with patch.object(prepare, 'decode_sources') as decode:
                with self.assertRaises(ValueError):
                    prepare.prepare('unused', state_directory=prepare.PARAMS_CONTROL_STATE, discovery_source=source)
                decode.assert_not_called()

    def test_inspector_uses_fixed_state(self):
        with patch.object(inspect, '_inspect_profile') as check:
            inspect.inspect_params_control('bundle', 'source')
            check.assert_called_once_with('bundle', 'source', prepare.PARAMS_CONTROL_STATE)

    def test_real_composition_and_binding_order(self):
        root = Path(__file__).parent
        read = lambda name: (root/name).read_text()
        builder = compose(*[read(name) for name in (
            'mcp_echo_control_inputs.py', 'mcp_fixture_compat.py', 'mcp_fixture_params.py')])
        args = (builder, *[read(name) for name in ('mcp_echo_control_evidence.py',
            'mcp_discovery_evidence.py', 'mcp_result_summary.py', 'mcp_wildcard_denial_evidence.py')])
        code = bootstrap.make_params_control_probe(*args)
        compile(code, '<params-bootstrap>', 'exec')
        self.assertLess(code.index('prepare.STATE=prepare.PARAMS_CONTROL_STATE'),
                        code.index("inspect=module("))
        self.assertIn('inspect.inspect_params_control', code)
        self.assertEqual(code.count('prepare.PARAMS_CONTROL_STATE'), 3)
        self.assertNotIn('prepare.COMPATIBLE_CONTROL_STATE', code)
        for factory, state in ((bootstrap.make_control_probe, 'CONTROL_STATE'),
                               (bootstrap.make_compatible_control_probe, 'COMPATIBLE_CONTROL_STATE')):
            old = factory(*args)
            self.assertIn('prepare.STATE=prepare.'+state, old)
            self.assertNotIn('prepare.PARAMS_CONTROL_STATE', old)

    def test_exclusive_flags(self):
        for options in ({'params': 1}, {'params': True, 'compatible': True},
                        {'params': True}, {'compatible': 1}):
            with self.assertRaises(ValueError):
                bootstrap._make_probe('pass', 'pass', 'pass', 'pass', **options)
        for source in ('', None, 'x'*16385):
            with self.assertRaises(ValueError):
                bootstrap.make_params_control_probe('pass', 'pass', 'pass', 'pass', source)

    def test_prepare_and_inspect_probes(self):
        for source, invocation in (
            (prepare.PARAMS_CONTROL_PROBE, 'state_directory=module.PARAMS_CONTROL_STATE'),
            (inspect.PARAMS_CONTROL_PROBE, 'module.inspect_params_control(sys.argv[3],sys.argv[4])')):
            compile(source, '<params-probe>', 'exec')
            self.assertIn(invocation, source)


if __name__ == '__main__':
    unittest.main()
