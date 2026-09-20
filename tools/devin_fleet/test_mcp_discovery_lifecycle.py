from copy import deepcopy
import unittest
from unittest.mock import patch
import mcp_discovery_lifecycle as life
from mcp_discovery_evidence import summarize
from test_mcp_discovery_evidence import payload,audit,NONCE


class DiscoveryLifecycleTests(unittest.TestCase):
    def test_fixed_adapters_and_namespace(self):
        with patch.object(life,'_run_probe',return_value={'passed':False}) as run:
            self.assertFalse(life.run_discovery({})['passed'])
        self.assertIs(run.call_args.kwargs['network'],life.discovery_probe_network)
        self.assertIs(run.call_args.kwargs['execute'],life.execute)
        self.assertEqual(run.call_args.kwargs['evidence_prefix'],'mcp-discovery-lifecycle-')

    def test_collection_remains_non_accepting(self):
        candidate=summarize(payload(),audit(),NONCE)
        bound={'tool_call_count':1,'exact_model_verified':True}
        with patch.object(life,'_collection',return_value=bound) as verify:
            result=life.collection(dict(binding=bound,discovery=candidate),preflight={})
        verify.assert_called_once_with(bound,preflight={})
        self.assertFalse(result['discovery']['passed'])

    def test_bad_candidate_refused(self):
        candidate=summarize(payload(),audit(),NONCE)
        bound={'tool_call_count':1,'exact_model_verified':True}
        for changes in ({'passed':True},{'tool_call_count':True},{'consistent':False},
                        {'audit_call_count':1},{'extra':False},{'exact_model_verified':False}):
            with self.subTest(changes=changes),patch.object(life,'_collection',return_value=bound):
                value=deepcopy(candidate);value.update(changes)
                with self.assertRaises(ValueError):life.collection(dict(binding=bound,discovery=value))


if __name__=='__main__':unittest.main()
