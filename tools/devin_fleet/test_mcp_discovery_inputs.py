"""Pure input preparation comparisons; never run a fixture or CLI."""
import hashlib
import json
from pathlib import PurePosixPath
import unittest
from unittest.mock import patch
import mcp_discovery_inputs as discovery
import mcp_probe_inputs as baseline
from machine_cli_smoke import DENY
from mcp_probe_binding import ARTIFACTS

WORK=PurePosixPath('/tmp/e-base-mcp-probe-12345678')
NONCE='a'*32
IDENTITY=(1,2)


class DiscoveryInputsTests(unittest.TestCase):
    def test_only_two_artifacts_change_and_original_deny_is_unchanged(self):
        before=list(DENY)
        original=baseline.build_inputs(WORK,NONCE,IDENTITY)
        actual=discovery.build_inputs(WORK,NONCE,IDENTITY)
        self.assertEqual(set(actual),ARTIFACTS)
        self.assertEqual(len(actual),9)
        self.assertEqual({name for name in actual if actual[name]!=original[name]},
                         {'config.json','prompt.txt'})
        self.assertEqual(DENY,before)
        self.assertEqual(baseline.build_inputs(WORK,NONCE,IDENTITY),original)
        source=json.loads(original['config.json']);target=json.loads(actual['config.json'])
        self.assertEqual(target['permissions'],
                         {'deny':[item for item in before if item!='mcp_list_tools'],
                          'allow':['mcp_list_tools']})
        target['permissions']=source['permissions']
        self.assertEqual(target,source)

    def test_call_and_other_capabilities_remain_denied(self):
        permissions=json.loads(discovery.build_inputs(WORK,NONCE,IDENTITY)['config.json'])['permissions']
        self.assertEqual(permissions['allow'],['mcp_list_tools'])
        self.assertNotIn('mcp_list_tools',permissions['deny'])
        for item in DENY:
            if item!='mcp_list_tools':self.assertIn(item,permissions['deny'])
        for item in ('mcp__*','mcp_call_tool','mcp_list_servers','mcp_read_resource','exec','request_scope'):
            self.assertIn(item,permissions['deny'])

    def test_inherited_secrets_are_dropped_but_source_digest_preserved(self):
        raw=b'{"mcpServers":{"existing":{"url":"SECRET_URL","env":{"TOKEN":"SECRET_TOKEN"},"args":["SECRET_ARG"]}}}'
        original=baseline.make_input_builder(raw)(WORK,NONCE,IDENTITY)
        actual=discovery.make_input_builder(raw)(WORK,NONCE,IDENTITY)
        self.assertEqual({name for name in actual if actual[name]!=original[name]},
                         {'config.json','prompt.txt'})
        servers=json.loads(actual['.devin/mcp_config.json'])['mcpServers']
        self.assertEqual(servers['existing'],{'command':'/usr/bin/false','disabled':True})
        self.assertFalse(servers['fleet-probe']['disabled'])
        self.assertEqual(actual['inherited-mcp.sha256'],hashlib.sha256(raw).hexdigest().encode()+b'\n')
        self.assertNotIn(b'SECRET',b'\n'.join(actual.values()))

    def test_build_keyword_options_preserve_baseline_artifacts(self):
        options=dict(inherited_servers=('one','two'),inherited_sha256='b'*64)
        original=baseline.build_inputs(WORK,NONCE,IDENTITY,**options)
        actual=discovery.build_inputs(WORK,NONCE,IDENTITY,**options)
        for name in ARTIFACTS-{'config.json','prompt.txt'}:
            self.assertEqual(actual[name],original[name])

    def test_factory_reuses_baseline_factory(self):
        original=baseline.build_inputs(WORK,NONCE,IDENTITY)
        with patch.object(baseline,'make_input_builder',return_value=lambda *args:original) as factory:
            discovery.make_input_builder(b'fixed-input')(WORK,NONCE,IDENTITY)
        factory.assert_called_once_with(b'fixed-input')
        self.assertEqual(json.loads(original['config.json'])['permissions']['allow'],[])

    def test_prompt_is_fixed_listing_only_without_secret_inputs(self):
        prompt=discovery.build_inputs(WORK,NONCE,IDENTITY)['prompt.txt'].decode()
        self.assertEqual(prompt,discovery.PROMPT)
        for fragment in ('mcp_list_tools exactly once','fixed server fleet-probe',
                         'do not execute','other servers','or retry','stop'):
            self.assertIn(fragment,prompt)
        self.assertNotIn(NONCE,prompt)
        self.assertNotIn(str(WORK),prompt)

    def test_unexpected_baseline_permissions_refused(self):
        original=baseline.build_inputs(WORK,NONCE,IDENTITY)
        config=json.loads(original['config.json']);config['permissions']['allow']=['exec']
        original['config.json']=json.dumps(config).encode()
        with patch.object(baseline,'build_inputs',return_value=original):
            with self.assertRaisesRegex(ValueError,'Exact baseline'):
                discovery.build_inputs(WORK,NONCE,IDENTITY)


if __name__=='__main__':unittest.main()
