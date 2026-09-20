"""Synthetic diagnostic summaries; no CLI, VM, or network actions."""
from copy import deepcopy
import json
import unittest
from mcp_result_summary import summarize,validate,TOOL,LIMITS,FLAGS

NONCE='a'*32


def payload():
    return {'session_id':'SECRET_SESSION','steps':[{'source':'agent','content':'permission denied SECRET_PROSE',
        'tool_calls':[{'function_name':TOOL,'arguments':{},'tool_call_id':'SECRET_CALL'}]},
        {'source':'tool','observation':{'results':[{'source_call_id':'SECRET_CALL','content':'Permission denied SECRET_RESULT'}]}}]}


class ResultSummaryTests(unittest.TestCase):
    def test_fixed_output_has_only_counters_and_bools(self):
        audit=''.join(NONCE+':'+s+'\n' for s in ('initialized','listed','called')).encode()
        value=summarize(payload(),audit,NONCE)
        self.assertIs(validate(value),value)
        self.assertEqual(value['expected_tool_count'],1)
        self.assertEqual(value['permission_denial_count'],1)
        self.assertTrue(value['audit_nonce_verified'])
        self.assertTrue(value['audit_discovery_sequence_observed'])
        self.assertEqual([value[k] for k in ('audit_initialization_count','audit_list_count','audit_call_count')],[1,1,1])
        self.assertEqual(set(value),set(LIMITS)|set(FLAGS))
        self.assertTrue(all(type(v) in (int,bool) for v in value.values()))
        raw=json.dumps(value)
        for secret in ('SECRET',TOOL,NONCE,'session_id','source_call_id'):
            self.assertNotIn(secret,raw)

    def test_agent_prose_is_never_observation_evidence(self):
        value=summarize({'steps':[{'source':'agent','content':'permission denied unknown tool server unavailable'}]},b'',NONCE)
        self.assertEqual(value['observation_count'],0)
        self.assertFalse(value['audit_nonce_verified'])
        self.assertEqual(value['audit_initialization_count'],0)

    def test_tool_classes_and_empty_arguments(self):
        data=payload()
        data['steps'][0]['tool_calls'] += [dict(function_name='mcp__SECRET__x',arguments={'secret':'SECRET_ARG'},tool_call_id='x'),
                                         dict(function_name='SECRET_SHELL',arguments={},tool_call_id='y')]
        value=summarize(data,b'',NONCE)
        self.assertEqual([value[k] for k in ('expected_tool_count','other_mcp_count','other_tool_count','arguments_empty_count')],[1,1,1,2])
        self.assertNotIn('SECRET',json.dumps(value))

    def test_generic_binding_is_exact_and_does_not_export_arguments(self):
        data=payload()
        call=data['steps'][0]['tool_calls'][0]
        call.update(function_name='mcp_call_tool',arguments={'server_name':'fleet-probe','tool_name':'echo','arguments':{}})
        value=summarize(data,b'',NONCE)
        self.assertEqual(value['generic_exact_target_count'],1)
        self.assertEqual(value['generic_linked_result_count'],1)
        self.assertEqual(value['generic_linked_denied_word_count'],1)
        self.assertEqual(value['generic_linked_policy_word_count'],1)
        self.assertNotIn('SECRET',json.dumps(value))
        data['steps'][1]['observation']['results'][0]['source_call_id']='other'
        self.assertEqual(summarize(data,b'',NONCE)['generic_linked_result_count'],0)
        call['arguments']['extra']='SECRET'
        self.assertEqual(summarize(data,b'',NONCE)['generic_exact_target_count'],0)

    def test_generic_mcp_names_are_classified_without_arguments(self):
        data=payload()
        data['steps'][0]['tool_calls'][0]['function_name']='mcp_list_tools'
        value=summarize(data,b'',NONCE)
        self.assertEqual(value['mcp_list_tools_count'],1)
        self.assertEqual(value['mcp_call_tool_count'],0)
        self.assertEqual(value['observation_policy_words_count'],1)

    def test_observation_classes_are_fixed_and_prefix_only(self):
        data={'steps':[{'source':'tool','observation':{'results':[{'content':s} for s in
              ('Unknown tool SECRET','MCP server unavailable SECRET','prefix permission denied SECRET','') ]}}]}
        value=summarize(data,b'',NONCE)
        self.assertEqual([value[k] for k in ('permission_denial_count','unknown_tool_count','unavailable_server_count','other_observation_count')],[0,1,1,2])

    def test_invalid_shapes_rejected_without_raw_data(self):
        cases=[{}, {'steps':[]},{'steps':[{}]},{'steps':[{'source':'SECRET'}]},
               {'steps':[{'source':'agent','tool_calls':['SECRET']}]},
               {'steps':[{'source':'tool','observation':{'results':[{'content':{'SECRET':1}}]}}]}]
        for data in cases:
            with self.subTest(data=data),self.assertRaises(ValueError) as error:
                summarize(data,b'',NONCE)
            self.assertNotIn('SECRET',str(error.exception))

    def test_bounds(self):
        for data in ({'steps':[{'source':'user'}]*257},
                     {'steps':[{'source':'agent','tool_calls':payload()['steps'][0]['tool_calls']*17}]},
                     {'steps':[{'source':'tool','observation':{'results':[{'content':''}]*17}}]},
                     {'steps':[{'source':'tool','observation':{'results':[{'content':'x'*65537}]}}]}):
            with self.assertRaises(ValueError):summarize(data,b'',NONCE)

    def test_invalid_audit_or_nonce_is_sanitized(self):
        for raw,nonce in ((b'SECRET\n',NONCE),(b'\xff\n',NONCE),(b'', 'SECRET'),('',NONCE),
                          ((('b'*32)+':called\n').encode(),NONCE),((NONCE+':called\n').encode()*65,NONCE)):
            with self.assertRaises(ValueError) as error:summarize(payload(),raw,nonce)
            self.assertNotIn('SECRET',str(error.exception))

    def test_validator_rejects_unknown_keys_coercions_and_inconsistent_counts(self):
        base=summarize(payload(),b'',NONCE)
        for changes in ({'SECRET':1},{'step_count':True},{'audit_nonce_verified':1},
                        {'other_tool_count':-1},{'expected_tool_count':4097},
                        {'arguments_empty_count':2},{'observation_count':0},{'audit_call_count':65}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):validate(dict(base,**changes))
        missing=deepcopy(base);del missing['step_count']
        with self.assertRaises(ValueError):validate(missing)

    def test_nonfinite_or_recursive_json_is_sanitized(self):
        data=payload();data['secret']=float('nan')
        with self.assertRaises(ValueError):summarize(data,b'',NONCE)
        data['secret']=data
        with self.assertRaises(ValueError):summarize(data,b'',NONCE)


if __name__=='__main__':unittest.main()
