"""Lossy synthetic status diagnostics; no CLI or authentication execution."""
import json
import unittest

from auth_status_shape import summarize


class AuthStatusShapeTests(unittest.TestCase):
    def test_fixed_markers_count_without_returning_values(self):
        secret = 'SYNTHETIC_PRIVATE_VALUE'
        raw = ('Logged in as ' + secret + '\nAuthenticated as ' + secret + '\nEmail: ' + secret +
               '\nAccount: ' + secret + '\nAuthentication Type: ' + secret +
               '\nLogged in: ' + secret + '\nNot logged in. synthetic diagnostic\n').encode()
        result = summarize(raw, 0)
        self.assertEqual(result['line_count'], 7)
        self.assertTrue(all(count == 1 for count in result['markers'].values()))
        self.assertEqual(set(result), {'returncode', 'line_count', 'markers',
            'raw_output_suppressed', 'authentication_verified', 'model_executed'})
        self.assertNotIn(secret, json.dumps(result))
        self.assertNotIn('hash', json.dumps(result))
        self.assertIs(result['authentication_verified'], False)
        self.assertIs(result['model_executed'], False)
        self.assertIs(result['raw_output_suppressed'], True)

    def test_mixed_positive_negative_never_authenticates(self):
        result = summarize(b'Logged in as synthetic\nNot logged in\nLogged in: false\n', 0)
        self.assertEqual(result['markers']['logged_in_as'], 1)
        self.assertEqual(result['markers']['not_logged_in'], 1)
        self.assertEqual(result['markers']['logged_in_label'], 1)
        self.assertFalse(result['authentication_verified'])

    def test_ansi_color_and_blank_lines_do_not_hide_markers(self):
        result = summarize(b'\n \t\n\x1b[32mLogged in as synthetic\x1b[0m\r\n', 0)
        self.assertEqual(result['line_count'], 1)
        self.assertEqual(result['markers']['logged_in_as'], 1)

    def test_unknown_text_and_substrings_do_not_match(self):
        result = summarize(b'prefix Logged in as synthetic\nnot logged in\n'
                           b'Not logged in but something\nEmail:\nAccount:\nrandom secret\n', 0)
        self.assertEqual(result['line_count'], 6)
        self.assertTrue(all(value == 0 for value in result['markers'].values()))

    def test_duplicate_marker_lines_are_counted_not_collapsed(self):
        result = summarize(b'Email: one\nEmail: two\nAuth type: one\nAuthentication Type: two', 0)
        self.assertEqual(result['markers']['email_label'], 2)
        self.assertEqual(result['markers']['auth_type_label'], 2)

    def test_empty_output_remains_unverified_diagnostic(self):
        result = summarize(b'', 0)
        self.assertEqual(result['line_count'], 0)
        self.assertTrue(all(value == 0 for value in result['markers'].values()))
        self.assertFalse(result['authentication_verified'])

    def test_exact_byte_limit_accepted_and_excess_rejected(self):
        result = summarize(b'x' * 65536, 0)
        self.assertEqual(result['line_count'], 1)
        with self.assertRaises(ValueError):
            summarize(b'x' * 65537, 0)

    def test_raw_type_and_invalid_utf8_rejected(self):
        for value in ('Email: synthetic', bytearray(b'Email: synthetic'), None, b'\xff'):
            with self.subTest(kind=type(value).__name__), self.assertRaises(ValueError):
                summarize(value, 0)

    def test_returncode_requires_integer_not_bool_or_float(self):
        for value in (True, False, 0.0, '0', None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                summarize(b'Logged in as synthetic', value)
        for value in (0, 1, -9):
            result = summarize(b'Logged in as synthetic', value)
            self.assertEqual(result['returncode'], value)
            self.assertFalse(result['authentication_verified'])

    def test_non_color_escape_sequence_is_not_general_terminal_interpretation(self):
        result = summarize(b'\x1b[2JLogged in as synthetic', 0)
        self.assertEqual(result['markers']['logged_in_as'], 0)
        self.assertFalse(result['authentication_verified'])


if __name__ == '__main__':
    unittest.main()
