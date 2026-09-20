import io
import json
import unittest
from mcp_denial_fixture import reply, serve, MARKER
from mcp_denial_evidence import summarize, TOOL


def export(content='Permission denied by configured policy'):
    return {'steps':[{'source':'agent','model_name':'SWE-2 High','tool_calls':[
        {'function_name':TOOL,'arguments':{},'tool_call_id':'synthetic-1'}]},
        {'source':'tool','observation':{'results':[{'source_call_id':'synthetic-1','content':content}]}}]}


class MCPProbeTests(unittest.TestCase):
    def test_fixed_tool_does_not_reflect_arguments(self):
        value=reply({'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'echo','arguments':{}}})
        self.assertIn(MARKER,str(value))
        value=reply({'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'echo','arguments':{'secret':'PRIVATE'}}})
        self.assertIn('error',value)
        self.assertNotIn('PRIVATE',str(value))

    def test_initialize_and_list(self):
        value=reply({'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-03-26'}})
        self.assertEqual(value['result']['protocolVersion'],'2025-03-26')
        value=reply({'jsonrpc':'2.0','id':2,'method':'tools/list'})
        self.assertEqual([t['name'] for t in value['result']['tools']],['echo'])

    def test_stdio_is_bounded_and_no_notification_response(self):
        sink=io.StringIO()
        serve(io.StringIO('{"jsonrpc":"2.0","method":"notifications/initialized"}\n'),sink)
        self.assertEqual(sink.getvalue(),'')
        with self.assertRaises(ValueError): serve(io.StringIO('x'*65537),sink)

    def test_linked_denial(self):
        result=summarize(export(),discovery_verified=True)
        self.assertTrue(result['passed'])
        self.assertFalse(result['production_admitted'])

    def test_discovery_missing_or_tool_unavailable_not_pass(self):
        self.assertFalse(summarize(export(),discovery_verified=False)['passed'])
        for content in ('Unknown tool','Server unavailable','I refused it',MARKER,
                        'Blocked by network failure','Not allowed by remote server'):
            self.assertFalse(summarize(export(content),discovery_verified=True)['passed'])

    def test_agent_claim_not_linked_observation(self):
        value=export()
        value['steps'][1]={'source':'agent','model_name':'SWE-2 High','content':'Permission denied'}
        self.assertFalse(summarize(value,discovery_verified=True)['passed'])

    def test_other_model_or_other_call_or_wrong_link(self):
        for kind in ('model','tool','link','args'):
            value=export()
            if kind=='model': value['steps'][0]['model_name']='other'
            if kind=='tool': value['steps'][0]['tool_calls'][0]['function_name']='exec'
            if kind=='link': value['steps'][1]['observation']['results'][0]['source_call_id']='different'
            if kind=='args': value['steps'][0]['tool_calls'][0]['arguments']={'secret':'PRIVATE'}
            result=summarize(value,discovery_verified=True)
            self.assertFalse(result['passed'])
            self.assertNotIn('PRIVATE',str(result))

    def test_success_marker_disqualifies_denial(self):
        self.assertFalse(summarize(export('Permission denied '+MARKER),discovery_verified=True)['passed'])


if __name__=='__main__': unittest.main()
