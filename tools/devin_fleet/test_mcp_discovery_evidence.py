"""Synthetic evidence only; never starts a CLI or fixture."""
from copy import deepcopy
import json
import unittest
from mcp_discovery_evidence import summarize

NONCE='a'*32


def audit(events=('initialized','listed')):
    return ''.join(NONCE+':'+event+'\n' for event in events).encode()


def payload():
    listing={'tools':[{'name':'echo','description':'SECRET_DESCRIPTION',
                      'inputSchema':{'type':'object','properties':{},'additionalProperties':False}}]}
    return {'session_id':'SECRET_SESSION','steps':[
        {'source':'agent','model_name':'swe-2-high','content':'SECRET_AGENT',
         'tool_calls':[{'function_name':'mcp_list_tools','arguments':{'server_name':'fleet-probe'},'tool_call_id':'SECRET_ID'}]},
        {'source':'tool','observation':{'results':[{'source_call_id':'SECRET_ID','content':json.dumps(listing)}]}}]}


class DiscoveryEvidenceTests(unittest.TestCase):
    def test_observed_grouped_envelope_is_exact(self):
        data=payload();item=data['steps'][1]['observation']['results'][0]
        group=dict(server_name='fleet-probe',resources=[],tools=json.loads(item['content'])['tools'])
        item['content']=json.dumps([group])
        self.assertTrue(summarize(data,audit(),NONCE)['consistent'])
        for changes in ({'resources':[{}]},{'resources':None},{'server_name':'other'},{'extra':[]}):
            changed=deepcopy(data)
            changed['steps'][1]['observation']['results'][0]['content']=json.dumps([dict(group,**changes)])
            self.check_negative(changed)

    def check_negative(self,data,raw=None):
        value=summarize(data,audit() if raw is None else raw,NONCE)
        self.assertFalse(value['consistent']);self.assertFalse(value['passed'])
        self.assertFalse(value['production_admitted'])
        return value

    def test_exact_candidate_is_not_acceptance_or_raw_export(self):
        value=summarize(payload(),audit(),NONCE)
        self.assertTrue(value['consistent']);self.assertFalse(value['passed'])
        self.assertFalse(value['production_admitted'])
        self.assertTrue(all(type(v) in (bool,int) for v in value.values()))
        self.assertNotIn('SECRET',json.dumps(value));self.assertNotIn(NONCE,json.dumps(value))

    def test_both_exact_argument_shapes_and_agent_observation_supported(self):
        for args in ({'server_name':'fleet-probe'},{'server':'fleet-probe'}):
            data=payload();data['steps'][0]['tool_calls'][0]['arguments']=args
            data['steps'][1].update(source='agent',model_name='SWE-2 High')
            self.assertTrue(summarize(data,audit(('initialized','initialized','listed')),NONCE)['consistent'])

    def test_extra_calls_arguments_or_duplicate_ids_are_negative(self):
        for args in ({},{'server_name':'other'},{'server_name':'fleet-probe','extra':1},
                     {'server_name':'fleet-probe','server':'fleet-probe'}):
            data=payload();data['steps'][0]['tool_calls'][0]['arguments']=args;self.check_negative(data)
        for identity in ('SECRET_ID','other'):
            data=payload();extra=deepcopy(data['steps'][0]['tool_calls'][0]);extra['tool_call_id']=identity
            data['steps'][0]['tool_calls'].append(extra);self.check_negative(data)

    def test_unlinked_duplicate_results_and_prose_are_negative(self):
        data=payload();data['steps'][1]['observation']['results'][0]['source_call_id']='other';self.check_negative(data)
        data=payload();data['steps'][1]['observation']['results']*=2;self.check_negative(data)
        for content in ('echo accepts empty args','```json\n{}\n```','{"tools":[]}',
                        '{"tools":[{"name":"echo","inputSchema":{}}]}'):
            data=payload();data['steps'][1]['observation']['results'][0]['content']=content;self.check_negative(data)
        data=payload();data['steps'][0]['content']=data['steps'][1]['observation']['results'][0]['content']
        del data['steps'][1]['observation'];self.check_negative(data)

    def test_unknown_schema_and_extra_tools_are_negative(self):
        for mutation in ('extra-key','extra-tool','wrong-schema','wrong-name'):
            data=payload();result=data['steps'][1]['observation']['results'][0];listing=json.loads(result['content'])
            if mutation=='extra-key':listing['extra']=True
            elif mutation=='extra-tool':listing['tools']*=2
            elif mutation=='wrong-schema':listing['tools'][0]['inputSchema']['additionalProperties']=True
            else:listing['tools'][0]['name']='other'
            result['content']=json.dumps(listing);self.check_negative(data)

    def test_extra_unlinked_result_and_result_before_call_are_negative(self):
        data=payload();extra=deepcopy(data['steps'][1]['observation']['results'][0])
        extra['source_call_id']='other';data['steps'][1]['observation']['results'].append(extra)
        self.check_negative(data)
        data=payload();data['steps'].reverse();self.check_negative(data)

    def test_same_agent_step_result_is_supported(self):
        data=payload();data['steps'][0]['observation']=data['steps'].pop()['observation']
        self.assertTrue(summarize(data,audit(),NONCE)['consistent'])

    def test_deep_json_is_rejected_with_fixed_error(self):
        data=payload();data['steps'][1]['observation']['results'][0]['content']='['*2000+'0'+']'*2000
        with self.assertRaisesRegex(ValueError,'Observation JSON depth exceeded'):
            summarize(data,audit(),NONCE)

    def test_brackets_and_escaped_quotes_inside_description_are_not_nesting(self):
        data=payload();result=data['steps'][1]['observation']['results'][0]
        listing=json.loads(result['content'])
        listing['tools'][0]['description']='[{'*100+'"\\"'+']}'*100
        result['content']=json.dumps(listing)
        self.assertTrue(summarize(data,audit(),NONCE)['consistent'])

    def test_duplicate_json_keys_and_nonfinite_are_rejected(self):
        for content in ('{"tools":[],"tools":[]}','{"tools":NaN}','{"tools":Infinity}'):
            data=payload();data['steps'][1]['observation']['results'][0]['content']=content
            with self.assertRaises(ValueError):summarize(data,audit(),NONCE)
        data=payload();data['extra']=float('nan')
        with self.assertRaises(ValueError):summarize(data,audit(),NONCE)

    def test_audit_order_empty_or_fixture_call_prevents_candidate(self):
        for events in (('initialized',),('listed','initialized'),('initialized','listed','called')):
            self.check_negative(payload(),audit(events))
        self.check_negative(payload(),b'')
        with self.assertRaises(ValueError):summarize(payload(),audit(),'b'*32)

    def test_all_agent_models_must_match(self):
        data=payload();data['steps'].append({'source':'agent','model_name':'other','content':'SECRET'})
        self.check_negative(data)
        data=payload();del data['steps'][0]['model_name'];self.check_negative(data)

    def test_bounds_and_bad_shapes(self):
        for data in ({'steps':[]},{'steps':[{'source':'user'}]*257},
                     {'steps':[{'source':'agent','tool_calls':payload()['steps'][0]['tool_calls']*17}]},
                     {'steps':[{'source':'tool','observation':{'results':payload()['steps'][1]['observation']['results']*17}}]},
                     {'steps':[{'source':'agent','tool_calls':['SECRET']}] }):
            with self.assertRaises(ValueError) as error:summarize(data,audit(),NONCE)
            self.assertNotIn('SECRET',str(error.exception))


if __name__=='__main__':unittest.main()
