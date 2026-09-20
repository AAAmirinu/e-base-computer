import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from mcp_config_shape import summarize, validate, collect


class ShapeTests(unittest.TestCase):
    def test_diagnostic_parse_preserves_untrusted_status_and_strict_refusal(self):
        with tempfile.TemporaryDirectory(prefix='mcp-shape-test-', dir='/tmp') as directory:
            for name in ('config.json','mcp_config.json'):
                path=Path(directory)/name
                path.write_bytes(b'{"mcpServers":{"SECRET":{"command":"SECRET"}}}')
                path.chmod(0o666)
            original_open=os.open
            def mapped_open(path, flags, *args, **kwargs):
                if path == '/':
                    return original_open(directory, flags)
                if path in ('home','agent','.config','devin'):
                    return os.dup(kwargs['dir_fd'])
                return original_open(path, flags, *args, **kwargs)
            with patch('mcp_config_shape.os.open', side_effect=mapped_open):
                strict=validate(collect())
                diagnostic=validate(collect(diagnostic=True))
            self.assertEqual(strict['files']['mcp']['status'],'unverified')
            self.assertFalse(strict['files']['mcp']['checks']['protected'])
            self.assertEqual(diagnostic['files']['mcp']['status'],'parsed_untrusted')
            self.assertEqual(diagnostic['files']['mcp']['server_count'],1)
            self.assertFalse(diagnostic['configuration_isolated'])
            self.assertNotIn('SECRET',repr(diagnostic))
            self.assertEqual((Path(directory)/'mcp_config.json').stat().st_mode & 0o777,0o666)

    def test_values_and_names_never_exported(self):
        raw=json.dumps({'mcpServers':{'SECRET_NAME':{'command':'SECRET_COMMAND','env':{'TOKEN':'SECRET_TOKEN'}},
                        'SECRET_REMOTE':{'url':'SECRET_URL','disabled':True}},'hooks':{'SECRET_HOOK':['SECRET']}}).encode()
        result=summarize(raw)
        self.assertNotIn('SECRET',repr(result))
        self.assertEqual(result['server_count'],2)
        self.assertEqual(result['disabled_count'],1)
        self.assertEqual(result['stdio_count'],1)
        self.assertEqual(result['remote_count'],1)
        self.assertEqual(result['hooks'],'nonempty')

    def test_empty_does_not_claim_isolation(self):
        result=summarize(b'{}')
        value=dict(files={'main':result,'mcp':result},raw_values_exported=False,model_executed=False,configuration_isolated=False)
        self.assertFalse(validate(value)['configuration_isolated'])
        value['configuration_isolated']=True
        with self.assertRaises(ValueError): validate(value)

    def test_invalid_duplicate_and_oversize_refused(self):
        for raw in (b'{"mcpServers":{},"mcpServers":{}}',b'[]',b'{"mcpServers":null}',b'x'*65537):
            with self.assertRaises(ValueError): summarize(raw)


if __name__=='__main__': unittest.main()
