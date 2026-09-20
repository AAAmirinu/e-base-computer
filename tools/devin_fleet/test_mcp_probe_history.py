import json
import unittest
from unittest.mock import patch
from mcp_probe_history import summarize,validate,PROBE,help_options,read_empty_workdir_inventory


class HistoryTests(unittest.TestCase):
    def test_empty_inventory_is_strict_and_work_bound(self):
        work='/tmp/e-base-mcp-probe-12345678'
        with patch('mcp_probe_catalog._capture',return_value=(b'[]',0)) as capture:
            result=read_empty_workdir_inventory(work,timeout=2)
        self.assertEqual(result['work'],work)
        self.assertEqual(result['session_inventory_scope'],'current_workdir')
        self.assertEqual(result['previous_sessions'],[])
        self.assertEqual(capture.call_args.args[1],work)
        self.assertEqual(capture.call_args.kwargs['timeout'],2)
        for raw,rc in ((b'[]',1),(b'[]',False),(b'{}',0),(b'null',0),(b'[{"id":"old"}]',0),(b'',0)):
            with self.subTest(raw=raw,rc=rc),patch('mcp_probe_catalog._capture',return_value=(raw,rc)):
                with self.assertRaises(ValueError): read_empty_workdir_inventory(work)

    def test_help_emits_only_option_names(self):
        self.assertEqual(help_options(b'Usage SECRET\n  --all All sessions\n --format <FORMAT>\n',0),['--all','--format'])
        with self.assertRaises(ValueError): help_options(b'--all',1)
        value=summarize(b'[]',0); value['list_help_options']=['SECRET']
        with self.assertRaises(ValueError): validate(value)

    def test_empty_is_not_global_history_proof(self):
        value=validate(summarize(b'[]',0))
        self.assertEqual(value['item_count'],0)
        self.assertFalse(value['history_verified'])

    def test_does_not_emit_session_ids_titles_or_unknown_keys(self):
        value=summarize(b'[{"id":"SECRET_ID","title":"SECRET_TITLE","SECRET_KEY":"SECRET_VALUE"}]',0)
        self.assertEqual(value['known_fields'],['id'])
        self.assertNotIn('SECRET',json.dumps(validate(value)))

    def test_failed_or_unknown_response_is_not_empty_history(self):
        for raw in (b'not json',b'{"sessions":[],"sessions":[]}',b'null'):
            value=validate(summarize(raw,1))
            self.assertEqual(value['kind'],'invalid')
            self.assertIsNone(value['item_count'])
        self.assertFalse(validate(summarize(b'[]',1))['history_verified'])

    def test_probe_compiles_and_cannot_claim_model_or_history(self):
        compile(PROBE,'trusted-history-probe','exec')
        for key in ('history_verified','model_executed'):
            value=summarize(b'[]',0); value[key]=True
            with self.assertRaises(ValueError): validate(value)


if __name__=='__main__': unittest.main()
