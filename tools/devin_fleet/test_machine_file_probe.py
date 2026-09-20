"""Synthetic file-probe helpers only; never launch the CLI or a model."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest

from machine_cli_smoke import (DENY, MODEL, file_probe_config,
                               summarize_file_probe, verify_probe_file)


class FileProbeConfigTests(unittest.TestCase):
    def setUp(self):
        self.work = Path('/tmp/e-base-file-probe-fixture')
        self.config = file_probe_config(self.work)

    def test_only_one_exact_output_path_allowed(self):
        self.assertEqual(self.config['permissions']['allow'],
                         ['Write(/tmp/e-base-file-probe-fixture/probe.txt)'])
        self.assertEqual(self.config['agent']['model'], MODEL)

    def test_reads_execution_and_edit_remain_denied(self):
        denied = self.config['permissions']['deny']
        for rule in ('read', 'Read(**)', 'exec', 'Exec(*)', 'edit', 'grep', 'glob'):
            with self.subTest(rule=rule):
                self.assertIn(rule, denied)
        for rule in DENY:
            if rule not in ('write', 'Write(**)'):
                with self.subTest(inherited_rule=rule):
                    self.assertIn(rule, denied)

    def test_sensitive_directories_remain_write_denied(self):
        for directory in ('home', 'etc', 'proc', 'sys', 'run', 'var', 'usr'):
            with self.subTest(directory=directory):
                self.assertIn('Write(/' + directory + '/**)',
                              self.config['permissions']['deny'])

    def test_probe_does_not_mutate_original_smoke_denials(self):
        before = list(DENY)
        self.assertNotIn('write', self.config['permissions']['deny'])
        self.assertNotIn('Write(**)', self.config['permissions']['deny'])
        self.config['permissions']['deny'].append('test-only')
        self.assertEqual(DENY, before)
        self.assertIn('write', DENY)
        self.assertIn('Write(**)', DENY)
        self.assertNotIn('test-only', file_probe_config(self.work)['permissions']['deny'])

    def test_external_configuration_discovery_disabled(self):
        self.assertEqual(self.config['read_config_from'],
                         {'cursor': False, 'windsurf': False, 'claude': False})


class FileProbeSummaryTests(unittest.TestCase):
    def setUp(self):
        self.work = Path('/tmp/e-base-file-probe-fixture')
        self.call = {'function_name': 'write', 'arguments': {
            'file_path': str(self.work / 'probe.txt'), 'content': 'EBASE_FILE_TOOL_OK\n'}}
        self.payload = {'steps': [{'source': 'agent', 'model_name': MODEL,
                                   'tool_calls': [self.call]}]}

    def summarize(self):
        return summarize_file_probe(self.payload, self.work)

    def test_single_exact_write_verified(self):
        for model in (MODEL, 'SWE-2 High'):
            with self.subTest(model=model):
                self.payload['steps'][0]['model_name'] = model
                result = self.summarize()
                self.assertEqual(result['tool_call_count'], 1)
                self.assertEqual(result['expected_write_call_count'], 1)
                self.assertTrue(result['all_calls_expected_write'])
                self.assertTrue(result['exact_model_verified'])
                self.assertFalse(result['shell_denial_verified'])
                self.assertFalse(result['production_admitted'])

    def test_wrong_path_rejected(self):
        self.call['arguments']['file_path'] = str(self.work / 'other.txt')
        self.assertFalse(self.summarize()['all_calls_expected_write'])
        self.assertEqual(self.summarize()['expected_write_call_count'], 0)

    def test_wrong_content_rejected(self):
        self.call['arguments']['content'] = 'EBASE_FILE_TOOL_OK'
        self.assertFalse(self.summarize()['all_calls_expected_write'])

    def test_exec_call_rejected(self):
        self.call['function_name'] = 'exec'
        self.assertFalse(self.summarize()['all_calls_expected_write'])

    def test_additional_call_rejected_even_if_identical_write(self):
        self.payload['steps'][0]['tool_calls'].append(copy.deepcopy(self.call))
        result = self.summarize()
        self.assertEqual(result['tool_call_count'], 2)
        self.assertFalse(result['all_calls_expected_write'])

    def test_additional_exec_call_rejected(self):
        self.payload['steps'].append({'source': 'tool', 'tool_calls': [
            {'function_name': 'exec', 'arguments': {'command': 'do-not-run'}}]})
        result = self.summarize()
        self.assertEqual(result['tool_call_count'], 2)
        self.assertEqual(result['expected_write_call_count'], 1)
        self.assertFalse(result['all_calls_expected_write'])

    def test_empty_calls_not_accepted(self):
        self.payload['steps'][0]['tool_calls'] = []
        result = self.summarize()
        self.assertEqual(result['tool_call_count'], 0)
        self.assertFalse(result['all_calls_expected_write'])

    def test_legacy_function_call_rejected(self):
        self.payload['steps'][0]['function_call'] = {'name': 'write', 'arguments': 'hidden'}
        self.assertFalse(self.summarize()['all_calls_expected_write'])

    def test_wrong_model_not_verified(self):
        for model in ('swe-2-medium', 'swe-2-max', 'other', None):
            with self.subTest(model=model):
                self.payload['steps'][0]['model_name'] = model
                self.assertFalse(self.summarize()['exact_model_verified'])

    def test_no_agent_model_evidence_not_verified(self):
        self.payload['steps'][0]['source'] = 'tool'
        self.assertFalse(self.summarize()['exact_model_verified'])

    def test_summary_contains_only_fixed_booleans_and_counts(self):
        secret = 'SYNTHETIC_DO_NOT_DISCLOSE_4d993'
        self.call['arguments']['content'] = secret
        self.payload['steps'][0]['text'] = secret
        self.payload['steps'][0]['output'] = secret
        result = self.summarize()
        self.assertEqual(set(result), {'tool_call_count', 'expected_write_call_count',
                                      'all_calls_expected_write', 'exact_model_verified',
                                      'shell_denial_verified', 'production_admitted'})
        self.assertTrue(all(type(value) in (bool, int) for value in result.values()))
        self.assertNotIn(secret, json.dumps(result))
        self.assertNotIn(str(self.work), json.dumps(result))

    def test_malformed_envelopes_raise_without_returning_raw_input(self):
        for payload in (None, {}, {'steps': []}, {'steps': ['secret']},
                        {'steps': [{'tool_calls': 'secret'}]}):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError) as caught:
                    summarize_file_probe(payload, self.work)
                self.assertNotIn('secret', str(caught.exception))


@unittest.skipUnless(os.name == 'posix' and hasattr(os, 'O_NOFOLLOW'),
                     'Descriptor and link rejection is validated on Linux')
class ProbeFileVerificationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.path = self.root / 'probe.txt'

    def test_exact_marker_with_one_newline_accepted(self):
        self.path.write_bytes(b'EBASE_FILE_TOOL_OK\n')
        self.assertTrue(verify_probe_file(self.path))

    def test_nonexact_markers_rejected(self):
        for payload in (b'', b'EBASE_FILE_TOOL_OK', b'EBASE_FILE_TOOL_OK\r\n',
                        b'EBASE_FILE_TOOL_OK\n\n', b' EBASE_FILE_TOOL_OK\n',
                        b'OTHER\n', b'EBASE_FILE_TOOL_OK\nextra'):
            with self.subTest(payload=payload):
                self.path.write_bytes(payload)
                self.assertFalse(verify_probe_file(self.path))

    def test_oversize_rejected(self):
        self.path.write_bytes(b'EBASE_FILE_TOOL_OK\n' + b'x' * 65)
        self.assertFalse(verify_probe_file(self.path))

    def test_symlink_rejected_without_following_target(self):
        target = self.root / 'target.txt'
        target.write_bytes(b'EBASE_FILE_TOOL_OK\n')
        self.path.symlink_to(target)
        with self.assertRaises(OSError):
            verify_probe_file(self.path)
        self.assertEqual(target.read_bytes(), b'EBASE_FILE_TOOL_OK\n')

    def test_hardlinked_file_rejected(self):
        self.path.write_bytes(b'EBASE_FILE_TOOL_OK\n')
        os.link(self.path, self.root / 'alias.txt')
        self.assertFalse(verify_probe_file(self.path))

    def test_directory_rejected(self):
        self.path.mkdir()
        self.assertFalse(verify_probe_file(self.path))

    def test_missing_file_is_not_success(self):
        with self.assertRaises(FileNotFoundError):
            verify_probe_file(self.path)


if __name__ == '__main__':
    unittest.main()
