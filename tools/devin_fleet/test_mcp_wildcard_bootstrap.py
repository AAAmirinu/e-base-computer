from pathlib import Path
import ast
import unittest
from unittest.mock import patch
import guest_mcp_wildcard as bootstrap


class BootstrapTests(unittest.TestCase):
    def sources(self):
        root = Path(__file__).parent
        return [(root/name).read_text() for name in ('mcp_wildcard_denial_inputs.py',
            'mcp_wildcard_denial_evidence.py', 'mcp_discovery_evidence.py', 'mcp_result_summary.py')]

    def test_real_sources_compile_with_fixed_state_and_collection(self):
        code = bootstrap.make_probe(*self.sources())
        compile(code, '<test>', 'exec')
        self.assertIn('prepare.STATE=prepare.WILDCARD_STATE', code)
        self.assertIn('inspect.inspect_wildcard(', code)
        self.assertIn('state_directory=prepare.WILDCARD_STATE', code)
        self.assertIn("result={'binding':binding,'wildcard':candidate}", code)
        self.assertEqual(code.count("print('EBASE_MCP_DISPATCH:'"), 1)
        self.assertLess(code.index("module('mcp_discovery_evidence'"),
                        code.index("evidence=module('trusted_discovery_evidence'"))

    def test_each_source_is_bounded(self):
        for index in range(4):
            for invalid in ('', None, 'x'*16385):
                sources = ['# trusted']*4; sources[index] = invalid
                with self.assertRaises(ValueError): bootstrap.make_probe(*sources)

    def test_dispatch_drift_refused(self):
        with patch.object(bootstrap.baseline, 'PROBE', ''):
            with self.assertRaises(ValueError): bootstrap.make_probe(*self.sources())

    def test_embedded_placeholders_are_not_rewritten(self):
        sources = ['# DISCOVERY_INPUT_SOURCE DISCOVERY_EVIDENCE_SOURCE '+str(i) for i in range(4)]
        code = bootstrap.make_probe(*sources)
        values = [node.value for node in ast.walk(ast.parse(code)) if isinstance(node, ast.Constant)]
        for source in sources: self.assertIn(source, values)

    def test_collector_drift_refused(self):
        with patch.object(bootstrap, 'COLLECT', bootstrap.COLLECT.replace('prepare.DISCOVERY_STATE', 'other')):
            with self.assertRaises(ValueError): bootstrap.make_probe(*self.sources())


if __name__ == '__main__': unittest.main()
