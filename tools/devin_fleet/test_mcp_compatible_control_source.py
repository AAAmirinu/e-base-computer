import hashlib
import json
from pathlib import Path
import types
import unittest
import mcp_echo_control_inputs as control
import mcp_fixture_compat as compat
from mcp_compatible_control_source import compose

class ComposedBuilderTests(unittest.TestCase):
    args=('/tmp/e-base-mcp-probe-abcdefgh','a'*32,(1,2))
    def module(self):
        source=compose(Path(control.__file__).read_text(),Path(compat.__file__).read_text())
        module=types.ModuleType('trusted_composed_builder')
        exec(compile(source,'<trusted-test-builder>','exec'),module.__dict__)
        return module

    def test_fresh_prepare_and_inspect_build_identical_inputs(self):
        raw=b'{"mcpServers":{"inherited":{"url":"SECRET"}}}'
        prepared=self.module().make_input_builder(raw)(*self.args)
        inspected=self.module().make_input_builder(raw)(*self.args)
        self.assertEqual(prepared,inspected)
        original=control.make_input_builder(raw)(*self.args)
        self.assertEqual(set(prepared),set(original))
        self.assertEqual({k for k in original if original[k]!=prepared[k]},{'fixture.py','runner.py'})
        self.assertNotIn(b'SECRET',b'\n'.join(prepared.values()))
        self.assertIn(hashlib.sha256(prepared['fixture.py']).hexdigest().encode(),prepared['runner.py'])

    def test_both_entrypoints_share_transformation(self):
        module=self.module()
        raw=b'{"mcpServers":{"inherited":{"url":"https://example.invalid"}}}'
        self.assertEqual(module.make_input_builder(raw)(*self.args),
            module.build_inputs(*self.args,inherited_servers=('inherited',),inherited_sha256=hashlib.sha256(raw).hexdigest()))

    def test_source_literals_not_rescanned_or_executed_by_compose(self):
        source=compose("raise RuntimeError('LITERAL _compat and <trusted-control-builder>')",'pass')
        self.assertIn('LITERAL _compat',source)
        compile(source,'<only-compile>','exec')

    def test_source_limits_include_composed_representation(self):
        for pair in ((None,'pass'),('','pass'),('pass','x'*16385),('#'+('x'*9000),'#'+('y'*9000))):
            with self.assertRaises(ValueError):compose(*pair)

if __name__=='__main__':unittest.main()
