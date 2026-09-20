import ast
from pathlib import Path
import unittest
from guest_mcp_wildcard import make_control_probe


class ControlBootstrapTests(unittest.TestCase):
    def sources(self):
        root=Path(__file__).parent
        return [(root/name).read_text() for name in ('mcp_echo_control_inputs.py',
            'mcp_echo_control_evidence.py','mcp_discovery_evidence.py','mcp_result_summary.py',
            'mcp_wildcard_denial_evidence.py')]

    def test_fixed_control_state_and_dependency_order(self):
        code=make_control_probe(*self.sources());compile(code,'<control>','exec')
        self.assertIn('prepare.STATE=prepare.CONTROL_STATE',code)
        self.assertIn('inspect.inspect_control(',code)
        self.assertIn('state_directory=prepare.CONTROL_STATE',code)
        self.assertIn("result={'binding':binding,'control':candidate}",code)
        self.assertNotIn('prepare.WILDCARD_STATE',code)
        self.assertLess(code.index("module('mcp_result_summary'"),code.index("module('mcp_wildcard_denial_evidence'"))
        self.assertLess(code.index("module('mcp_wildcard_denial_evidence'"),code.index("evidence=module('trusted_discovery_evidence'"))
        self.assertEqual(code.count("print('EBASE_MCP_DISPATCH:'"),1)

    def test_every_source_bounded(self):
        for index in range(5):
            for invalid in (None,'','x'*16385):
                sources=['# trusted']*5;sources[index]=invalid
                with self.assertRaises(ValueError):make_control_probe(*sources)

    def test_placeholders_in_all_sources_preserved(self):
        sources=['# CONTROL_SEQUENCE_SOURCE DISCOVERY_INPUT_SOURCE '+str(i) for i in range(5)]
        code=make_control_probe(*sources)
        values=[n.value for n in ast.walk(ast.parse(code)) if isinstance(n,ast.Constant)]
        for source in sources:self.assertIn(source,values)


if __name__=='__main__':unittest.main()
