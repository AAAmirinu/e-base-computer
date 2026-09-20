import json
import os
from pathlib import Path
import tempfile
import types
import unittest
import catalog_log_summary as original
from compatible_log_summary import compose,START,END,PATTERNS

class CompatibleLogTests(unittest.TestCase):
    def setUp(self):
        self.module=types.ModuleType('trusted_test_logs')
        exec(compile(compose(Path(original.__file__).read_text()),'<trusted-logs>','exec'),self.module.__dict__)

    def test_fixed_window_and_markers_no_text(self):
        self.assertEqual(self.module.START,START);self.assertEqual(self.module.END,END)
        value=self.module.classify(b'fleet-probe Traceback (most recent call last)\nValueError: Bounded string or integer request id required SECRET\nBrokenPipeError')
        self.assertEqual(value['fixture_compatible_id_error'],1)
        self.assertEqual(value['broken_pipe'],1)
        self.assertNotIn('SECRET',json.dumps(value))

    def test_real_bounded_reader_selects_only_fixed_mtime(self):
        with tempfile.TemporaryDirectory(dir='/tmp') as directory:
            root=Path(directory)
            for suffix,stamp,raw in (('1',START+1,b'fleet-probe JSONDecodeError SECRET'),('2',START-1,b'BrokenPipeError'),('3',END+1,b'BrokenPipeError')):
                path=root/('devin_2026-09-20T00-00-00_'+suffix+'.log')
                path.write_bytes(raw);path.chmod(0o600);os.utime(path,(stamp,stamp))
            (root/'credentials.json').write_text('SECRET')
            result=self.module.collect(directory)
            self.assertEqual(result['candidate_count'],1)
            self.assertEqual(result['categories']['json_error'],1)
            self.assertEqual(result['categories']['broken_pipe'],0)
            self.assertFalse(result['attempt_bound'])
            self.assertNotIn('SECRET',json.dumps(result))

    def test_old_reader_unchanged_and_source_bounds(self):
        self.assertNotEqual(original.START,START)
        self.assertNotEqual(original.PATTERNS,PATTERNS)
        for source in ('',None,'#'+'x'*16384):
            with self.assertRaises(ValueError):compose(source)

    def test_error_context_same_line_only(self):
        value=self.module.classify(b'fleet-probe tools/call -32602 Unsupported fixed probe request SECRET\n_meta resources/list')
        for key in ('invalid_params','fixture_name','tool_call'):
            self.assertEqual(value['fixture_error_line_'+key],1)
        self.assertEqual(value['fixture_error_line_metadata'],0)
        self.assertEqual(value['fixture_error_line_resource_list'],0)
        self.assertNotIn('SECRET',json.dumps(value))
        value=self.module.classify(b'def reply(): return "Unsupported fixed probe request"')
        self.assertEqual(value['fixture_error_line_source_code'],1)
        self.assertEqual(value['fixture_error_line_invalid_params'],0)

    def test_serialized_source_is_ambiguous_and_long_lines_incomplete(self):
        raw=b'{"source":"def reply(): return -32602; Unsupported fixed probe request fleet-probe tools/call"}'
        value=self.module.classify(raw)
        self.assertEqual(value['fixture_error_line_invalid_params'],1)
        self.assertEqual(value['fixture_error_line_source_code'],1)
        long=self.module.classify(b'x'*2200+raw)
        self.assertEqual(long['fixture_error'],1)
        self.assertEqual(long['fixture_error_line_invalid_params'],0)

    def test_structured_event_fields_not_serialized_source(self):
        raw=json.dumps({'fields':{'message':'Unsupported fixed probe request','error':{'code':-32602},'method':'tools/call'},'token':'SECRET'}).encode()
        value=self.module.classify(raw)
        self.assertEqual(value['event_fixture_error'],1)
        self.assertEqual(value['event_invalid_params'],1)
        self.assertEqual(value['event_tool_call'],1)
        source=self.module.classify(json.dumps({'source':raw.decode()}).encode())
        self.assertEqual(source['event_fixture_error'],0)
        self.assertEqual(source['fixture_line_json_without_message'],1)
        self.assertNotIn('SECRET',json.dumps(value))

    def test_nonjson_duplicate_and_unknown_method_are_distinct(self):
        raw=b'plain Unsupported fixed probe request\n{"message":"Unsupported fixed probe request","message":"duplicate"}\n'
        value=self.module.classify(raw)
        self.assertEqual(value['fixture_line_nonjson'],1)
        self.assertEqual(value['fixture_line_invalid_json'],1)
        self.assertEqual(value['event_fixture_error'],0)

if __name__=='__main__':unittest.main()
