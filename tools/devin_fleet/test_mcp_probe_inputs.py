import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from mcp_probe_inputs import build_inputs, make_input_builder
from mcp_probe_reservation import prepare_attempt
from mcp_probe_audit import summarize_nonce_audit


class InputsTests(unittest.TestCase):
    def test_inherited_override_drops_remote_values_and_binds_source(self):
        import hashlib
        raw=b'{"mcpServers":{"existing":{"url":"SECRET","env":{"TOKEN":"SECRET"}}}}'
        inputs=make_input_builder(raw)(Path('/tmp/e-base-mcp-probe-12345678'),'a'*32,(1,2))
        config=json.loads(inputs['.devin/mcp_config.json'])['mcpServers']
        self.assertEqual(config['existing'],{'command':'/usr/bin/false','disabled':True})
        self.assertNotIn('SECRET',repr(config))
        self.assertEqual(inputs['inherited-mcp.sha256'],hashlib.sha256(raw).hexdigest().encode()+b'\n')

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='mcp-input-test-', dir='/tmp')
        self.addCleanup(temporary.cleanup)
        state = Path(temporary.name)
        state.chmod(0o700)
        self.work, self.reservation = prepare_attempt(state, build_inputs, previous_sessions=[])
        self.addCleanup(shutil.rmtree, self.work)

    def test_fixed_configuration_and_empty_environment_launcher(self):
        config = json.loads((self.work/'config.json').read_bytes())
        self.assertNotIn('mcpServers', config)
        self.assertEqual(config['permissions']['allow'], [])
        self.assertIn('mcp__*', config['permissions']['deny'])
        server = json.loads((self.work/'.devin/mcp_config.json').read_bytes())['mcpServers']
        self.assertEqual(set(server), {'fleet-probe'})
        self.assertEqual(server['fleet-probe']['command'], '/usr/bin/env')
        self.assertEqual(server['fleet-probe']['args'],
                         ['-i', '/usr/bin/python3', '-I', str(self.work/'runner.py')])

    def run_fixture(self, messages):
        server = json.loads((self.work/'.devin/mcp_config.json').read_bytes())['mcpServers']['fleet-probe']
        return subprocess.run([server['command']] + server['args'],
                              input=''.join(json.dumps(m)+'\n' for m in messages),
                              capture_output=True, text=True, timeout=5, cwd=self.work)

    def test_real_stdio_discovery_records_reserved_nonce(self):
        result = self.run_fixture([
            {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize'},
            {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'}])
        self.assertEqual(result.returncode, 0, result.stderr)
        responses = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(responses[1]['result']['tools'][0]['name'], 'echo')
        audit = summarize_nonce_audit((self.work/'fixture-events.log').read_bytes(), self.reservation['nonce'])
        self.assertTrue(audit['discovery_sequence_observed'])
        self.assertEqual(audit['tool_call_count'], 0)
        self.assertFalse(audit['cli_session_bound'])

    def test_real_stdio_call_is_always_audited(self):
        result = self.run_fixture([{'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                                    'params': {'name': 'echo', 'arguments': {}}}])
        self.assertEqual(result.returncode, 0, result.stderr)
        audit = summarize_nonce_audit((self.work/'fixture-events.log').read_bytes(), self.reservation['nonce'])
        self.assertEqual(audit['tool_call_count'], 1)

    def test_inode_replacement_refuses_before_protocol_response(self):
        audit = self.work/'fixture-events.log'
        audit.rename(self.work/'original-audit')
        audit.touch(mode=0o600)
        result = self.run_fixture([{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize'}])
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')
        self.assertEqual(audit.read_bytes(), b'')

    def test_modified_fixture_is_not_executed(self):
        (self.work/'fixture.py').write_bytes(b'raise RuntimeError("UNTRUSTED_EXECUTED")\n')
        result = self.run_fixture([{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize'}])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Trusted source changed', result.stderr)
        self.assertNotIn('UNTRUSTED_EXECUTED', result.stderr)
        self.assertEqual(result.stdout, '')


if __name__ == '__main__': unittest.main()
