from copy import deepcopy
import json
import unittest
from test_mcp_discovery_evidence import payload, audit, NONCE
from mcp_wildcard_denial_evidence import summarize


def sequence():
    data = payload()
    data['steps'].extend([
        {'source': 'agent', 'model_name': 'swe-2-high', 'tool_calls': [{
            'function_name': 'mcp_call_tool', 'tool_call_id': 'call2',
            'arguments': {'server_name': 'fleet-probe', 'tool_name': 'echo', 'arguments': {}}}]},
        {'source': 'tool', 'observation': {'results': [{
            'source_call_id': 'call2', 'content': 'Permission denied by policy'}]}}])
    return data


class SequenceTests(unittest.TestCase):
    def test_observed_fixed_target_sentence_not_rule_attribution(self):
        sentence="Permission to call MCP tool 'echo' on server 'fleet-probe' was denied."
        data=sequence();data['steps'][3]['observation']['results'][0]['content']=sentence
        result=summarize(data,audit(),NONCE)
        self.assertTrue(result['fixed_target_refusal_observed'])
        self.assertTrue(result['consistent']);self.assertFalse(result['matched_rule_verified'])
        self.assertFalse(result['permission_denial_accepted'])
        for content in (sentence.replace('echo','other'),sentence.replace('fleet-probe','other'),
                        'Example: '+sentence,sentence+'suffix',sentence.replace('denied','allowed')):
            data['steps'][3]['observation']['results'][0]['content']=content
            self.check_negative(data)

    def check_negative(self, data, raw=None):
        result = summarize(data, audit() if raw is None else raw, NONCE)
        self.assertFalse(result['consistent'])
        return result

    def test_candidate_is_not_acceptance_or_rule_attribution(self):
        result = summarize(sequence(), audit(), NONCE)
        self.assertTrue(result['consistent'])
        for key in ('passed', 'production_admitted', 'permission_denial_accepted', 'matched_rule_verified'):
            self.assertFalse(result[key])
        self.assertTrue(all(type(v) in (int, bool) for v in result.values()))
        self.assertNotIn('SECRET', json.dumps(result))

    def test_reordering_and_same_step_are_inconclusive(self):
        data = sequence(); data['steps'][1], data['steps'][2] = data['steps'][2], data['steps'][1]
        self.check_negative(data)
        data = sequence(); data['steps'][2]['observation'] = data['steps'][1]['observation']
        del data['steps'][1]['observation']; self.check_negative(data)

    def test_wrong_target_ids_extra_calls_results(self):
        for mutation in ('target', 'duplicate-id', 'foreign-result', 'extra-call', 'extra-result'):
            data = sequence()
            if mutation == 'target': data['steps'][2]['tool_calls'][0]['arguments']['tool_name'] = 'other'
            elif mutation == 'duplicate-id': data['steps'][2]['tool_calls'][0]['tool_call_id'] = 'SECRET_ID'
            elif mutation == 'foreign-result': data['steps'][3]['observation']['results'][0]['source_call_id'] = 'other'
            elif mutation == 'extra-call': data['steps'][2]['tool_calls'] *= 2
            else: data['steps'][3]['observation']['results'] *= 2
            self.check_negative(data)

    def test_execution_and_unconfirmed_refusal_fail(self):
        for text in ('Permission denied EBASE_MCP_FIXTURE_CALLED', 'Unknown tool',
                     'I think permission was denied', 'blocked', 'server unavailable',
                     'permission deniedness', 'blocked by permission policyish'):
            data = sequence(); data['steps'][3]['observation']['results'][0]['content'] = text
            self.check_negative(data)
        self.check_negative(sequence(), audit(('initialized', 'listed', 'called')))
        self.check_negative(sequence(), b'')

    def test_model_and_schema_mismatch(self):
        data = sequence(); data['steps'][2]['model_name'] = 'other'; self.check_negative(data)
        data = sequence(); data['steps'][1]['observation']['results'][0]['content'] = '{}'
        self.check_negative(data)

    def test_malformed_unlinked_evidence_rejected(self):
        data = sequence()
        data['steps'][3]['observation']['results'].append({'source_call_id': 'foreign', 'content': '{"a":1,"a":2}'})
        with self.assertRaises(ValueError): summarize(data, audit(), NONCE)


if __name__ == '__main__': unittest.main()
