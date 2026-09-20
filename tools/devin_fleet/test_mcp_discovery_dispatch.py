"""Bootstrap contract tests only; no model, fixture, or VM invocation."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import guest_mcp_discovery as discovery

INPUT='def make_input_builder(raw): return None\n'
EVIDENCE='def summarize(*args): return {}\n'


class DiscoveryDispatchTests(unittest.TestCase):
    def test_generated_probe_compiles_and_has_one_output(self):
        code=discovery.make_probe(INPUT,EVIDENCE)
        compile(code,'<test>','exec')
        self.assertEqual(code.count("print('EBASE_MCP_DISPATCH:'"),1)
        self.assertNotIn('inspect.inspect_prepared(sys.argv[3])',code)
        self.assertIn('inspect.inspect_discovery(sys.argv[3],',code)
        self.assertLess(code.index('prepare.STATE=prepare.DISCOVERY_STATE'),code.index("inspect=module('guest_mcp_inspect'"))
        self.assertLess(code.index('prepare.STATE=prepare.DISCOVERY_STATE'),code.index("dispatch=module('guest_mcp_dispatch'"))

    def test_collector_precedes_classification_and_checks_exact_bindings(self):
        code=discovery.make_probe(INPUT,EVIDENCE)
        self.assertLess(code.index('binding=collector.collect('),code.index('candidate=evidence.summarize('))
        self.assertIn('state_directory=prepare.DISCOVERY_STATE',code)
        for fragment in ("stage='after'","binding['export_sha256']","binding['audit_sha256']",
                         "binding['launch_sha256']","binding['process_result_sha256']",
                         "stop['reservation_sha256']","expected!=captured['inputs']",
                         "collector._read(claim,name,1048576)!=original",
                         "result={'binding':binding,'discovery':candidate}"):
            self.assertIn(fragment,code)

    def test_invalid_actions_or_arity_fail_before_loading_any_source(self):
        code=discovery.make_probe(INPUT,EVIDENCE)
        source="raise AssertionError('Source must not load')"
        for arguments in ([],[source]*5+['unknown'],[source]*5+['preflight','extra'],
                          [source]*5+['dispatch'],[source]*5+['collect','stop']):
            with self.subTest(arguments=len(arguments)),patch.object(sys,'argv',['probe']+arguments):
                with self.assertRaisesRegex(ValueError,'Fixed discovery action'):
                    exec(code,{})

    def test_valid_action_arities_reach_trusted_source_load(self):
        code=discovery.make_probe(INPUT,EVIDENCE)
        source="raise RuntimeError('SOURCE_BOUNDARY')"
        for action,tail in (('preflight',[]),('dispatch',['admission']),('collect',['stop','inspection'])):
            with patch.dict(sys.modules),patch.object(sys,'argv',['probe',source,'inspect','bundle','support','dispatch',action]+tail):
                with self.assertRaisesRegex(RuntimeError,'SOURCE_BOUNDARY'):
                    exec(code,{})

    def test_replacement_drift_fails_closed(self):
        original=discovery.baseline.PROBE
        anchors=("prepare=module('guest_mcp_prepare',sys.argv[1])",
                 '    inspect.inspect_prepared(sys.argv[3])',
                 "    result=sys.modules['mcp_probe_collect'].collect(sys.argv[7].encode(),inspection_lease_id=sys.argv[8])\n")
        for anchor in anchors:
            for replacement in ('',anchor+anchor):
                with self.subTest(anchor=anchor),patch.object(discovery.baseline,'PROBE',original.replace(anchor,replacement)):
                    with self.assertRaisesRegex(ValueError,'bootstrap drift'):
                        discovery.make_probe(INPUT,EVIDENCE)

    def test_missing_or_duplicate_output_refused(self):
        original=discovery.baseline.PROBE
        marker="print('EBASE_MCP_DISPATCH:'+json.dumps(result))"
        for changed in (original.replace(marker,''),original+'\n'+marker):
            with patch.object(discovery.baseline,'PROBE',changed):
                with self.assertRaisesRegex(ValueError,'single dispatch output'):
                    discovery.make_probe(INPUT,EVIDENCE)

    def test_source_bounds_and_real_sources(self):
        for bad in (None,b'bytes','', 'x'*16385,'あ'*6000):
            for pair in ((bad,EVIDENCE),(INPUT,bad)):
                with self.assertRaises(ValueError):discovery.make_probe(*pair)
        root=Path(discovery.__file__).parent
        compile(discovery.make_probe((root/'mcp_discovery_inputs.py').read_text(),
                                     (root/'mcp_discovery_evidence.py').read_text()),'<real>','exec')


if __name__=='__main__':unittest.main()
