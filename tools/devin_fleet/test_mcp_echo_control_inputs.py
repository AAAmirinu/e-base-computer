import json
import unittest
from unittest.mock import patch
import mcp_echo_control_inputs as control
import mcp_probe_inputs as original
from machine_cli_smoke import DENY


class ControlTests(unittest.TestCase):
    args=('/tmp/e-base-mcp-probe-12345678','a'*32,(1,2))

    def test_only_permissions_and_prompt_change(self):
        old=original.build_inputs(*self.args);new=control.build_inputs(*self.args)
        self.assertEqual(set(new),set(old))
        self.assertEqual({k for k in old if old[k]!=new[k]},{'config.json','prompt.txt'})
        before=json.loads(old['config.json']);after=json.loads(new['config.json'])
        rules=after['permissions']
        self.assertEqual(rules['allow'],['mcp_list_tools','mcp_call_tool','mcp__fleet-probe__echo'])
        self.assertEqual(rules['deny'],[r for r in DENY if r not in (*control.DISPATCH,'mcp__*')])
        after['permissions']=before['permissions'];self.assertEqual(after,before)
        self.assertEqual(original.build_inputs(*self.args),old)

    def test_other_servers_disabled_and_fixture_unmodified(self):
        raw=b'{"mcpServers":{"inherited":{"url":"SECRET","env":{"TOKEN":"SECRET"}}}}'
        value=control.make_input_builder(raw)(*self.args)
        servers=json.loads(value['.devin/mcp_config.json'])['mcpServers']
        self.assertEqual(servers['inherited'],{'command':'/usr/bin/false','disabled':True})
        self.assertNotIn(b'SECRET',b'\n'.join(value.values()))
        old=original.make_input_builder(raw)(*self.args)
        for key in set(old)-{'config.json','prompt.txt'}:self.assertEqual(old[key],value[key])

    def test_changed_baseline_refused(self):
        inputs=original.build_inputs(*self.args)
        config=json.loads(inputs['config.json']);config['permissions']['allow']=['exec']
        inputs['config.json']=json.dumps(config).encode()
        with patch.object(original,'build_inputs',return_value=inputs):
            with self.assertRaises(ValueError):control.build_inputs(*self.args)

    def test_prompt_neutral_bounded_and_no_retry(self):
        text=control.build_inputs(*self.args)['prompt.txt'].decode()
        self.assertIn('without predicting whether permission will be granted',text)
        for fragment in ('mcp_list_tools exactly once','mcp_call_tool exactly once','empty arguments {}','permissions or retry','stop'):
            self.assertIn(fragment,text)


if __name__=='__main__':unittest.main()
