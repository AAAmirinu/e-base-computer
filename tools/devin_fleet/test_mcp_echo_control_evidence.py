import json
import unittest
from test_mcp_wildcard_denial_evidence import sequence,audit,NONCE
from mcp_echo_control_evidence import summarize,MARKER


class ControlEvidenceTests(unittest.TestCase):
    def data(self,text=MARKER):
        data=sequence();data['steps'][3]['observation']['results'][0]['content']=text
        return data

    def test_exact_marker_and_mcp_result_are_nonaccepting_candidates(self):
        for text in (MARKER,json.dumps({'content':[{'type':'text','text':MARKER}],'isError':False})):
            result=summarize(self.data(text),audit(('initialized','listed','called')),NONCE)
            self.assertTrue(result['consistent'])
            for key in ('matched_rule_verified','permission_denial_accepted','passed','production_admitted'):
                self.assertFalse(result[key])

    def test_marker_without_execution_or_wrong_order_not_success(self):
        for events in (('initialized','listed'),('initialized','called','listed'),
                       ('initialized','listed','called','called')):
            self.assertFalse(summarize(self.data(),audit(events),NONCE)['consistent'])

    def test_prose_error_extra_content_and_false_numeric_rejected(self):
        values=['Example: '+MARKER,'Permission denied',
                json.dumps({'content':[{'type':'text','text':MARKER}],'isError':True}),
                json.dumps({'content':[{'type':'text','text':MARKER}],'isError':0}),
                json.dumps({'content':[{'type':'text','text':MARKER},{'type':'text','text':'extra'}],'isError':False})]
        for text in values:
            with self.subTest(text=text):
                self.assertFalse(summarize(self.data(text),audit(('initialized','listed','called')),NONCE)['consistent'])

    def test_marker_only_in_agent_text_does_not_count(self):
        data=self.data('other');data['steps'][2]['content']=MARKER
        self.assertFalse(summarize(data,audit(('initialized','listed','called')),NONCE)['consistent'])

    def test_wrong_target_result_link_and_model_rejected(self):
        for mutation in ('target','link','model'):
            data=self.data()
            if mutation=='target':data['steps'][2]['tool_calls'][0]['arguments']['tool_name']='other'
            elif mutation=='link':data['steps'][3]['observation']['results'][0]['source_call_id']='other'
            else:data['steps'][2]['model_name']='other'
            self.assertFalse(summarize(data,audit(('initialized','listed','called')),NONCE)['consistent'])

    def test_wrong_nonce_and_ambiguous_json_refused(self):
        with self.assertRaises(ValueError):
            summarize(self.data(),audit(('initialized','listed','called')),'b'*32)
        for text in ('{"isError":false,"isError":true}','{"value":NaN}','['*100+'0'+']'*100):
            with self.assertRaises(ValueError):
                summarize(self.data(text),audit(('initialized','listed','called')),NONCE)

    def test_extra_result_never_consistent(self):
        data=self.data();data['steps'][3]['observation']['results']*=2
        self.assertFalse(summarize(data,audit(('initialized','listed','called')),NONCE)['consistent'])


if __name__=='__main__':unittest.main()
