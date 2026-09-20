"""Synthetic turn/capture binding tests. No VM or source-code execution."""
import copy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import validation_snapshot_input as binding


class TurnValidationBindingTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path.cwd() / 'synthetic-turn-only'
        self.path = self.directory / 'turn.json'
        self.snapshot = {'base': 'b' * 40, 'changed': ['src/a.py'],
                         'fingerprints': {'src/a.py': 'c' * 64},
                         'manifest_sha256': 'd' * 64}
        self.turn = {'schema': 1, 'phase': 'awaiting_validation',
                     'validation_passed': False, 'committed': False,
                     'operation_id': 'a' * 32,
                     'migration_epoch': 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
                     'sequence': 2, 'role': 'machine',
                     'sandbox_id': 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
                     'snapshot': copy.deepcopy(self.snapshot), 'base': 'b' * 40}
        self.capture = {key: self.turn[key] for key in
                        ('operation_id', 'migration_epoch', 'sequence', 'role', 'sandbox_id', 'base')}
        self.capture.update(snapshot_directory=str(self.directory / 'source-snapshot'),
                            manifest_sha256='d' * 64,
                            source_checkpoint=copy.deepcopy(self.snapshot))
        self.evidence = {'capture': self.capture, 'capture_sha256': 'e' * 64}
        self.expected_epoch = self.turn['migration_epoch']

    def invoke(self, raw=None, path=None):
        if raw is None:
            raw = json.dumps(self.turn).encode()
        with patch.object(binding, '_directory') as directory, \
                patch.object(binding, '_file', return_value=raw) as reader, \
                patch.object(binding.Path, 'resolve', lambda value: value):
            result = binding.load_turn_binding(path or self.path, self.evidence,
                                               expected_epoch=self.expected_epoch)
        directory.assert_called_once_with(self.directory)
        reader.assert_called_once_with(self.path, 1024 * 1024)
        return result

    def test_matching_turn_returns_exact_binding_digests(self):
        raw = json.dumps(self.turn).encode()
        result = self.invoke(raw)
        self.assertEqual(result, {
            'turn_sha256': hashlib.sha256(raw).hexdigest(), 'capture_sha256': 'e' * 64,
            **{key: self.turn[key] for key in
               ('operation_id', 'migration_epoch', 'sequence', 'role', 'sandbox_id')},
            'manifest_sha256': 'd' * 64, 'base': 'b' * 40})

    def test_current_registration_epoch_required(self):
        for value in (None, 'invalid', 'cccccccc-cccc-4ccc-8ccc-cccccccccccc'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.expected_epoch = value
                self.invoke()

    def test_capture_sequence_bool_or_float_is_not_integer_sequence(self):
        self.turn['sequence'] = 1
        for value in (True, 1.0):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.capture['sequence'] = value
                self.invoke()

    def test_phase_must_be_awaiting_validation(self):
        for phase in ('prepared', 'inspection_pending', 'inspection_stopped', 'held', None):
            with self.subTest(phase=phase):
                self.turn['phase'] = phase
                with self.assertRaises(ValueError):
                    self.invoke()

    def test_validation_and_commit_flags_must_be_literal_false(self):
        for key in ('validation_passed', 'committed'):
            for value in (True, 0, None, 'false'):
                with self.subTest(key=key, value=value):
                    self.turn[key] = value
                    with self.assertRaises(ValueError):
                        self.invoke()
            self.turn[key] = False

    def test_schema_must_be_integer_one(self):
        for value in (True, 2, '1', None):
            with self.subTest(value=value):
                self.turn['schema'] = value
                with self.assertRaises(ValueError):
                    self.invoke()

    def test_each_identity_mismatch_rejected(self):
        replacements = {'operation_id': 'f' * 32,
                        'migration_epoch': 'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
                        'sequence': 3, 'role': 'stdlib',
                        'sandbox_id': 'dddddddd-dddd-4ddd-8ddd-dddddddddddd'}
        original = copy.deepcopy(self.turn)
        for key, value in replacements.items():
            with self.subTest(key=key):
                self.turn = dict(original, **{key: value})
                with self.assertRaises(ValueError):
                    self.invoke()

    def test_matching_but_malformed_identities_rejected(self):
        original_turn, original_capture = copy.deepcopy(self.turn), copy.deepcopy(self.capture)
        for key, value in (('operation_id', 'A' * 32), ('sequence', True), ('sequence', -1),
                           ('migration_epoch', 'not-uuid'), ('sandbox_id', 'not-uuid')):
            with self.subTest(key=key, value=value):
                self.turn = dict(original_turn, **{key: value})
                self.capture = dict(original_capture, **{key: value})
                self.evidence['capture'] = self.capture
                with self.assertRaises(ValueError):
                    self.invoke()

    def test_maintenance_capture_without_operation_binding_rejected(self):
        for key in ('operation_id', 'migration_epoch', 'sequence'):
            with self.subTest(key=key):
                value = self.capture.pop(key)
                with self.assertRaises(ValueError):
                    self.invoke()
                self.capture[key] = value

    def test_snapshot_content_mismatch_rejected(self):
        self.turn['snapshot']['fingerprints']['src/a.py'] = 'f' * 64
        with self.assertRaises(ValueError):
            self.invoke()

    def test_manifest_digest_mismatch_rejected(self):
        self.capture['manifest_sha256'] = 'f' * 64
        with self.assertRaises(ValueError):
            self.invoke()

    def test_base_mismatch_rejected(self):
        self.turn['base'] = 'f' * 40
        with self.assertRaises(ValueError):
            self.invoke()

    def test_turn_from_other_directory_rejected_before_read(self):
        with patch.object(binding, '_file') as reader:
            with self.assertRaises(ValueError):
                binding.load_turn_binding(self.directory / 'other.json', self.evidence,
                                          expected_epoch=self.expected_epoch)
        reader.assert_not_called()

    def test_partial_json_and_nonobjects_rejected(self):
        for raw in (b'', b'{"schema":1', b'null', b'[]'):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    self.invoke(raw)

    def test_duplicate_json_keys_rejected(self):
        raw = json.dumps(self.turn).encode()
        raw = b'{"phase":"held",' + raw[1:]
        with self.assertRaises(ValueError):
            self.invoke(raw)

    def test_duplicate_nested_snapshot_keys_rejected(self):
        raw = json.dumps(self.turn).replace('"snapshot": {', '"snapshot": {"base":"other",', 1).encode()
        with self.assertRaises(ValueError):
            self.invoke(raw)

    def test_missing_partial_receipt_rejected(self):
        with patch.object(binding, '_directory'), \
                patch.object(binding.Path, 'resolve', lambda value: value), \
                patch.object(binding, '_file', side_effect=FileNotFoundError):
            with self.assertRaises(FileNotFoundError):
                binding.load_turn_binding(self.path, self.evidence, expected_epoch=self.expected_epoch)


if __name__ == '__main__':
    unittest.main()
