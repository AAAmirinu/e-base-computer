import json
import unittest
from mcp_discovery_shape import summarize,validate,FLAGS,COUNTERS


def export(content):
    return {'steps':[{'source':'agent','content':'SECRET_PROSE','tool_calls':[
        {'function_name':'mcp_list_tools','arguments':{'server_name':'fleet-probe'},'tool_call_id':'SECRET_ID'}]},
        {'source':'tool','observation':{'results':[{'source_call_id':'SECRET_ID','content':content}]}}]}


class ShapeTests(unittest.TestCase):
    def test_metadata_is_finite_and_never_exports_values(self):
        group={'server_name':'fleet-probe','tools':[],'status':'connected'}
        value=summarize(export(json.dumps([group])))
        self.assertTrue(value['group_has_status']);self.assertTrue(value['group_extra_connected'])
        self.assertEqual(value['group_unknown_metadata_count'],0)
        del group['status'];group['SECRET_KEY']='SECRET_VALUE'
        value=summarize(export(json.dumps([group])))
        self.assertEqual(value['group_unknown_metadata_count'],1)
        self.assertNotIn('SECRET',json.dumps(value))

    def test_grouped_fixed_server_schema(self):
        group={'server_name':'fleet-probe','tools':[{'name':'echo','inputSchema':{'type':'object','properties':{},'additionalProperties':False}}]}
        value=summarize(export(json.dumps([group])))
        self.assertTrue(value['grouped_fixed_server']);self.assertTrue(value['grouped_echo_schema'])
        self.assertEqual(value['grouped_tool_count'],1)
        self.assertEqual(value['grouped_extra_group_fields'],0)
        group['server_name']='SECRET';group['tools'][0]['inputSchema']['additionalProperties']=True
        value=summarize(export(json.dumps([group])))
        self.assertFalse(value['grouped_fixed_server']);self.assertFalse(value['grouped_echo_schema'])
        self.assertNotIn('SECRET',json.dumps(value))

    def test_fixed_nonsecret_shapes(self):
        for key in ('inputSchema','input_schema','parameters'):
            tool={'name':'echo',key:{'type':'object','properties':{},'additionalProperties':False},'SECRET_KEY':'SECRET_VALUE'}
            for listing in ([tool],{'tools':[tool]}):
                value=summarize(export(json.dumps(listing)))
                self.assertTrue(value['echo_name_present']);self.assertTrue(value['empty_object_schema_present'])
                self.assertEqual(value['tool_element_count'],1);self.assertTrue(value['has_'+key])
                self.assertEqual(set(value),set(FLAGS)|set(COUNTERS))
                self.assertTrue(all(type(v) in (bool,int) for v in value.values()))
                self.assertNotIn('SECRET',json.dumps(value))

    def test_markdown_is_diagnostic_not_json(self):
        value=summarize(export('```json\n{"tools":[]}\n```'))
        self.assertTrue(value['json_fence']);self.assertTrue(value['markdown_prefix'])
        self.assertFalse(value['json_valid'])

    def test_exact_arguments_required_before_content_classification(self):
        for arguments in ({},{'server_name':'other'},{'server':'fleet-probe','extra':True}):
            data=export('{"tools":[]}');data['steps'][0]['tool_calls'][0]['arguments']=arguments
            value=summarize(data)
            self.assertFalse(value['exact_list_call']);self.assertFalse(value['linked_result'])
            self.assertEqual(value['content_length'],0)

    def test_unlinked_extra_or_prior_result_does_not_classify(self):
        data=export('{"tools":[]}');data['steps'][1]['observation']['results'][0]['source_call_id']='other'
        self.assertFalse(summarize(data)['linked_result'])
        data=export('{"tools":[]}');data['steps'][1]['observation']['results']*=2
        self.assertFalse(summarize(data)['linked_result'])
        data=export('{"tools":[]}');data['steps'].reverse()
        self.assertFalse(summarize(data)['linked_result'])

    def test_duplicate_nonfinite_depth_array_bounds(self):
        for content in ('{"tools":[],"tools":[]}','{"x":NaN}','{"x":1e999}',
                        '['*65+'0'+']'*65,json.dumps([{}]*257)):
            with self.assertRaises(ValueError):summarize(export(content))

    def test_known_nested_keys_without_exporting_values(self):
        value=summarize(export('{"result":{"content":{"server":"SECRET","server_name":"SECRET"}}}'))
        for key in ('result','content','server','server_name'):self.assertTrue(value['has_'+key])
        self.assertFalse(value['tools_array']);self.assertNotIn('SECRET',json.dumps(value))

    def test_invalid_shapes_and_validator(self):
        for payload in ({},{'steps':[]},{'steps':[{'source':'user'}]*257}):
            with self.assertRaises(ValueError):summarize(payload)
        good=summarize(export('{}'))
        for change in ({'SECRET':True},{'json_valid':1},{'content_length':True},{'tool_element_count':257}):
            with self.assertRaises(ValueError):validate(dict(good,**change))


if __name__=='__main__':unittest.main()
