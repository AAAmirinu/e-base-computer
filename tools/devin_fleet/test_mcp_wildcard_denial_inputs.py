import json
import unittest
from unittest.mock import patch
import mcp_probe_inputs as original
import mcp_wildcard_denial_inputs as candidate
from machine_cli_smoke import DENY


class WildcardInputsTests(unittest.TestCase):
    args = ('/tmp/e-base-mcp-probe-12345678', 'a'*32, (1, 2))

    def test_only_config_and_prompt_change(self):
        baseline = original.build_inputs(*self.args)
        actual = candidate.build_inputs(*self.args)
        self.assertEqual(set(actual), set(baseline))
        self.assertEqual({k for k in actual if actual[k] != baseline[k]},
                         {'config.json', 'prompt.txt'})
        self.assertEqual(original.build_inputs(*self.args), baseline)
        left, right = (json.loads(x['config.json']) for x in (baseline, actual))
        right['permissions'] = left['permissions']
        self.assertEqual(left, right)

    def test_wildcard_and_every_unrelated_deny_preserved(self):
        rules = json.loads(candidate.build_inputs(*self.args)['config.json'])['permissions']
        self.assertEqual(rules['allow'], list(candidate.DISPATCH))
        self.assertEqual(rules['deny'], [r for r in DENY if r not in candidate.DISPATCH])
        self.assertIn('mcp__*', rules['deny'])
        self.assertIn('mcp_list_servers', rules['deny'])

    def test_inherited_servers_stay_disabled_and_secrets_absent(self):
        raw = b'{"mcpServers":{"existing":{"url":"SECRET","env":{"TOKEN":"SECRET"}}}}'
        actual = candidate.make_input_builder(raw)(*self.args)
        servers = json.loads(actual['.devin/mcp_config.json'])['mcpServers']
        self.assertEqual(servers['existing'], {'command': '/usr/bin/false', 'disabled': True})
        self.assertNotIn(b'SECRET', b'\n'.join(actual.values()))

    def test_changed_baseline_rejected(self):
        baseline = original.build_inputs(*self.args)
        config = json.loads(baseline['config.json'])
        config['permissions']['allow'] = ['exec']
        baseline['config.json'] = json.dumps(config).encode()
        with patch.object(original, 'build_inputs', return_value=baseline):
            with self.assertRaises(ValueError): candidate.build_inputs(*self.args)

    def test_prompt_bounded_to_fixture_and_no_retry(self):
        prompt = candidate.build_inputs(*self.args)['prompt.txt'].decode()
        self.assertEqual(prompt, candidate.PROMPT)
        for text in ('mcp_list_tools exactly once', 'mcp_call_tool exactly once',
                     'tool echo', 'empty arguments {}', 'permissions or retry', 'stop'):
            self.assertIn(text, prompt)

    def test_missing_or_duplicate_test_rules_rejected(self):
        for rule in (*candidate.DISPATCH, 'mcp__*'):
            for rules in ([r for r in DENY if r != rule], [*DENY, rule]):
                with self.subTest(rule=rule, count=rules.count(rule)):
                    with patch.object(candidate, 'DENY', rules), patch.object(
                            original, 'DENY', rules):
                        with self.assertRaises(ValueError): candidate.build_inputs(*self.args)


if __name__ == '__main__': unittest.main()
