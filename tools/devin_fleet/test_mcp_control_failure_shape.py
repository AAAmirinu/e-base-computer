import unittest
import mcp_control_failure_shape as shape

class FailureShapeTests(unittest.TestCase):
    def payload(self,text):
        return {'steps':[{'source':'agent','tool_calls':[{'function_name':'mcp_call_tool',
            'tool_call_id':'one','arguments':shape.TARGETS[0]}]},
            {'source':'tool','observation':{'results':[{'source_call_id':'one','content':text}]}}]}

    def test_fixed_error_indicators_no_raw_output(self):
        value=shape.summarize(self.payload('secret: MCP error -32602: Unsupported fixed probe request'),b'','a'*32)
        self.assertEqual(value,dict(unique_linked_result=True,fixture_error_literal_present=True,
            invalid_params_code_present=True,marker_present=False))

    def test_agent_text_does_not_count(self):
        payload=self.payload('other')
        payload['steps'][0]['text']='Unsupported fixed probe request -32602 EBASE_MCP_FIXTURE_CALLED'
        value=shape.summarize(payload,b'','a'*32)
        self.assertFalse(any(value[k] for k in shape.KEYS[1:]))

    def test_wrong_link_and_duplicate_are_inconclusive(self):
        payload=self.payload('Unsupported fixed probe request')
        row=payload['steps'][1]['observation']['results'][0]
        row['source_call_id']='other'
        self.assertFalse(shape.summarize(payload,b'','a'*32)['unique_linked_result'])
        row['source_call_id']='one'
        payload['steps'][1]['observation']['results'].append(dict(row))
        self.assertFalse(shape.summarize(payload,b'','a'*32)['unique_linked_result'])

    def test_wire_contract_rejects_extra_or_nonbool(self):
        for value in ({},dict.fromkeys(shape.KEYS,0),dict.fromkeys(shape.KEYS,False)|{'raw':'secret'}):
            with self.assertRaises(ValueError):shape.validate(value)

if __name__=='__main__':unittest.main()
