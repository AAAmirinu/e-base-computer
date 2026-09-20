"""Pure export classification tests: no CLI, shell, filesystem, or model runs."""
import copy
import json
import unittest

from machine_cli_smoke import shell_observation_structure, summarize_shell_probe


class ShellObservationStructureTests(unittest.TestCase):
    KEYS = {'source_is_agent', 'source_is_tool', 'linked_to_call', 'content_kind',
            'has_error_field', 'has_denied_word', 'has_rejected_word',
            'has_permission_word', 'has_policy_word', 'starts_error'}

    def payload(self, content, *, source='tool', identity='call', error=False):
        item = {'source_call_id': identity, 'content': content}
        if error:
            item['error'] = 'SYNTHETIC_PRIVATE_ERROR'
        return {'steps': [
            {'source': 'agent', 'tool_calls': [{'tool_call_id': 'call',
                'function_name': 'exec', 'arguments': {'command': 'SYNTHETIC_PRIVATE_COMMAND'}}]},
            {'source': source, 'observation': {'results': [item]}},
        ]}

    def test_link_and_fixed_keyword_flags(self):
        result = shell_observation_structure(self.payload(
            'Error: permission denied; rejected by policy', error=True))
        self.assertEqual(result, [{
            'source_is_agent': False, 'source_is_tool': True, 'linked_to_call': True,
            'content_kind': 'text', 'has_error_field': True, 'has_denied_word': True,
            'has_rejected_word': True, 'has_permission_word': True,
            'has_policy_word': True, 'starts_error': True}])

    def test_other_identity_not_linked(self):
        for identity in ('other', None, 42):
            with self.subTest(identity=identity):
                result = shell_observation_structure(self.payload('ok', identity=identity))[0]
                self.assertFalse(result['linked_to_call'])

    def test_source_is_mapped_to_booleans_not_returned(self):
        for source, agent, tool in (('agent', True, False), ('tool', False, True),
                                    ('SYNTHETIC_PRIVATE_SOURCE', False, False)):
            with self.subTest(source=source):
                result = shell_observation_structure(self.payload('ok', source=source))[0]
                self.assertIs(result['source_is_agent'], agent)
                self.assertIs(result['source_is_tool'], tool)
                self.assertNotIn('SYNTHETIC_PRIVATE_SOURCE', json.dumps(result))

    def test_content_types_use_only_fixed_kind_names(self):
        for content, expected in (('secret', 'text'), (['secret'], 'list'),
                                   ({'secret': 'value'}, 'object'), (None, 'other'),
                                   (123, 'other'), (False, 'other')):
            with self.subTest(content=content):
                result = shell_observation_structure(self.payload(content))[0]
                self.assertEqual(result['content_kind'], expected)
                self.assertEqual(set(result), self.KEYS)
                self.assertTrue(all(type(value) is bool for key, value in result.items()
                                    if key != 'content_kind'))

    def test_sensitive_text_arguments_and_ids_not_returned(self):
        secret = 'SYNTHETIC_PRIVATE_CONTENT_74e2'
        payload = self.payload({'nested': [secret], 'permission': 'denied'},
                               identity='SYNTHETIC_PRIVATE_ID', error=True)
        result = shell_observation_structure(payload)
        encoded = json.dumps(result)
        for forbidden in (secret, 'SYNTHETIC_PRIVATE_COMMAND', 'SYNTHETIC_PRIVATE_ID',
                          'SYNTHETIC_PRIVATE_ERROR', 'arguments', 'nested'):
            self.assertNotIn(forbidden, encoded)
        self.assertEqual(set(result[0]), self.KEYS)

    def test_no_observations_returns_empty_list(self):
        self.assertEqual(shell_observation_structure({'steps': [
            {'source': 'agent', 'text': 'permission denied'}]}), [])

    def test_absent_keywords_are_false(self):
        result = shell_observation_structure(self.payload('completed'))[0]
        for key in ('has_error_field', 'has_denied_word', 'has_rejected_word',
                    'has_permission_word', 'has_policy_word', 'starts_error'):
            self.assertIs(result[key], False)


class ShellProbeSummaryTests(unittest.TestCase):
    def setUp(self):
        self.command = '/usr/bin/touch /tmp/e-base-shell-probe-fixture/shell-executed'
        self.call = {'function_name': 'exec', 'tool_call_id': 'fixed-call',
                     'arguments': {'command': self.command}}
        self.result = {'source_call_id': 'fixed-call', 'content': 'Permission denied'}
        self.payload = {'steps': [
            {'source': 'agent', 'tool_calls': [self.call]},
            {'source': 'tool', 'observation': {'results': [self.result]}},
        ]}

    def summarize(self, canary=False):
        return summarize_shell_probe(self.payload, self.command, canary)

    def test_one_linked_denial_and_absent_canary_verified(self):
        summary = self.summarize()
        self.assertEqual(summary, {
            'tool_call_count': 1, 'expected_exec_call_count': 1,
            'linked_denial_observed': True, 'shell_canary_exists': False,
            'shell_denial_verified': True, 'production_admitted': False})

    def test_supported_denial_phrases_case_insensitive(self):
        for text in ('PERMISSION DENIED', 'Tool execution denied by policy',
                     'Not allowed by policy', 'Blocked by configuration'):
            with self.subTest(text=text):
                self.result['content'] = text
                self.assertTrue(self.summarize()['shell_denial_verified'])

    def test_observed_command_specific_denial_verified(self):
        self.result['content'] = (
            'Permission to run the command "' + self.command +
            '" was denied. The user declined to allow command execution.')
        self.assertTrue(self.summarize()['linked_denial_observed'])
        self.assertTrue(self.summarize()['shell_denial_verified'])

    def test_command_specific_denial_for_different_command_rejected(self):
        self.result['content'] = (
            'Permission to run the command "/usr/bin/true" was denied. '
            'The user declined to allow command execution.')
        self.assertFalse(self.summarize()['linked_denial_observed'])
        self.assertFalse(self.summarize()['shell_denial_verified'])

    def test_command_specific_denial_negations_rejected(self):
        for content in (
            'Permission to run the command "' + self.command + '" was not denied.',
            'Permission to run the command "' + self.command + '" was granted.',
            'It is false that permission to run the command "' + self.command + '" was denied.',
        ):
            with self.subTest(content=content):
                self.result['content'] = content
                self.assertFalse(self.summarize()['shell_denial_verified'])

    def test_command_specific_denial_in_agent_text_not_evidence(self):
        self.payload['steps'] = [{'source': 'agent', 'tool_calls': [self.call],
            'text': 'Permission to run the command "' + self.command + '" was denied.'}]
        self.assertFalse(self.summarize()['shell_denial_verified'])

    def test_agent_denial_claim_without_observation_is_not_evidence(self):
        self.payload['steps'] = [{'source': 'agent', 'tool_calls': [self.call],
                                 'text': 'Permission denied. Tool execution denied.'}]
        self.assertFalse(self.summarize()['shell_denial_verified'])

    def test_negative_or_quoted_denial_is_not_evidence(self):
        for content in ('Not blocked by policy', 'The output says permission denied'):
            with self.subTest(content=content):
                self.result['content'] = content
                self.assertFalse(self.summarize()['shell_denial_verified'])

    def test_user_observation_is_not_evidence(self):
        self.payload['steps'][1]['source'] = 'user'
        self.assertFalse(self.summarize()['shell_denial_verified'])

    def test_denial_claim_without_call_is_not_evidence(self):
        self.payload['steps'][0]['tool_calls'] = []
        self.assertFalse(self.summarize()['shell_denial_verified'])

    def test_unlinked_observation_is_not_evidence(self):
        self.result['source_call_id'] = 'different-call'
        self.assertFalse(self.summarize()['linked_denial_observed'])
        self.assertFalse(self.summarize()['shell_denial_verified'])

    def test_missing_observation_identity_is_not_evidence(self):
        del self.result['source_call_id']
        self.assertFalse(self.summarize()['shell_denial_verified'])

    def test_wrong_command_not_verified(self):
        self.call['arguments']['command'] = '/usr/bin/true'
        summary = self.summarize()
        self.assertEqual(summary['expected_exec_call_count'], 0)
        self.assertFalse(summary['shell_denial_verified'])

    def test_wrong_tool_not_verified(self):
        self.call['function_name'] = 'write'
        self.assertFalse(self.summarize()['shell_denial_verified'])

    def test_additional_call_not_verified_even_if_same_request(self):
        self.payload['steps'][0]['tool_calls'].append(copy.deepcopy(self.call))
        summary = self.summarize()
        self.assertEqual(summary['tool_call_count'], 2)
        self.assertFalse(summary['shell_denial_verified'])

    def test_additional_unrelated_call_not_verified(self):
        self.payload['steps'].append({'source': 'agent', 'tool_calls': [
            {'function_name': 'read', 'arguments': {'path': '/synthetic'}}]})
        self.assertFalse(self.summarize()['shell_denial_verified'])

    def test_existing_canary_overrides_denial_observation(self):
        summary = self.summarize(canary=True)
        self.assertTrue(summary['linked_denial_observed'])
        self.assertTrue(summary['shell_canary_exists'])
        self.assertFalse(summary['shell_denial_verified'])

    def test_successful_tool_observation_does_not_prove_denial(self):
        self.result['content'] = 'Command finished with exit code 0'
        self.assertFalse(self.summarize()['shell_denial_verified'])

    def test_summary_never_returns_raw_arguments_or_content(self):
        secret = 'SYNTHETIC_PRIVATE_7c325'
        self.call['arguments']['extra'] = secret
        self.result['content'] = 'Permission denied: ' + secret
        summary = self.summarize()
        self.assertEqual(set(summary), {
            'tool_call_count', 'expected_exec_call_count', 'linked_denial_observed',
            'shell_canary_exists', 'shell_denial_verified', 'production_admitted'})
        self.assertTrue(all(type(value) in (bool, int) for value in summary.values()))
        self.assertNotIn(secret, json.dumps(summary))
        self.assertNotIn(self.command, json.dumps(summary))

    def test_empty_payload_is_not_verified(self):
        for payload in (None, {}, {'steps': []}):
            with self.subTest(payload=payload):
                self.assertFalse(summarize_shell_probe(payload, self.command, False)
                                 ['shell_denial_verified'])


if __name__ == '__main__':
    unittest.main()
