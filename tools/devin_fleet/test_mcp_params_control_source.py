import hashlib
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

import mcp_echo_control_inputs as control
import mcp_fixture_compat as compat
import mcp_fixture_params as params
from mcp_params_control_source import compose, IMPORT


class ParamsBuilderTests(unittest.TestCase):
    args = ('/tmp/e-base-mcp-probe-abcdefgh', 'a'*32, (1, 2))

    def sources(self):
        return [Path(m.__file__).read_text() for m in (control, compat, params)]

    def module(self):
        module = types.ModuleType('test_params_builder')
        source = compose(*self.sources())
        with patch.dict(sys.modules, {'mcp_fixture_compat': None}):
            exec(compile(source, '<test-params-builder>', 'exec'), module.__dict__)
            self.assertIsNone(sys.modules['mcp_fixture_compat'])
        return module

    def test_independent_reconstruction_and_hash(self):
        raw = b'{"mcpServers":{"inherited":{"url":"SECRET"}}}'
        original = control.make_input_builder(raw)(*self.args)
        actual = self.module().make_input_builder(raw)(*self.args)
        self.assertEqual(actual, self.module().make_input_builder(raw)(*self.args))
        self.assertEqual(actual, params.adapt_inputs(original))
        self.assertEqual(set(actual), set(original))
        self.assertEqual({k for k in original if original[k] != actual[k]}, {'fixture.py', 'runner.py'})
        self.assertNotIn(b'SECRET', b'\n'.join(actual.values()))
        self.assertEqual(actual['runner.py'].count(hashlib.sha256(actual['fixture.py']).hexdigest().encode()), 1)

    def test_entrypoints_identical(self):
        raw = b'{"mcpServers":{"inherited":{"url":"https://example.invalid"}}}'
        module = self.module()
        self.assertEqual(module.make_input_builder(raw)(*self.args), module.build_inputs(
            *self.args, inherited_servers=('inherited',), inherited_sha256=hashlib.sha256(raw).hexdigest()))

    def test_dependency_drift_rejected(self):
        source = self.sources()
        for replacement in ('', IMPORT + IMPORT):
            with self.assertRaises(ValueError):
                compose(source[0], source[1], source[2].replace(IMPORT, replacement))

    def test_limits_and_compile_only(self):
        for values in ((None, 'pass', IMPORT), ('', 'pass', IMPORT), ('x'*16385, 'pass', IMPORT),
                       ('#'+'x'*8000, '#'+'y'*8000, IMPORT+'#'+'z'*1000)):
            with self.assertRaises(ValueError):
                compose(*values)
        compile(compose('raise RuntimeError("not executed")', 'pass', IMPORT), '<test>', 'exec')


if __name__ == '__main__':
    unittest.main()
