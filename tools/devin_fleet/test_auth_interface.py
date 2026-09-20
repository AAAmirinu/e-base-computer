"""Pure parsing of synthetic interface output; never runs the CLI or VM."""
import json
import unittest

from inspect_auth_interface import parse_interface


class AuthInterfaceParsingTests(unittest.TestCase):
    def setUp(self):
        self.value = dict(binary_sha256='a' * 64,
            commands=[dict(args=['--version'], returncode=0, options=[], versions=['3000.6.2']),
                      dict(args=['auth', 'status', '--help'], returncode=0, options=['--help'], versions=[])],
            credentials_explicitly_read=False, auth_status_executed=False, model_executed=False,
            literal_contexts=[dict(marker='Not logged in', context='synthetic static binary text')])
        self.prefix = b'Sandbox e-base-machine started successfully\n'

    def raw(self):
        return json.dumps(self.value).encode()

    def test_plain_json_is_accepted(self):
        self.assertEqual(parse_interface(self.raw()), self.value)

    def test_exact_single_startup_prefix_is_accepted(self):
        self.assertEqual(parse_interface(self.prefix + self.raw() + b'\n'), self.value)

    def test_crlf_startup_and_pretty_json_are_accepted(self):
        raw = self.prefix.replace(b'\n', b'\r\n') + json.dumps(self.value, indent=2).encode()
        self.assertEqual(parse_interface(raw), self.value)

    def test_other_or_repeated_preamble_is_rejected(self):
        for prefix in (self.prefix + self.prefix,
                       b'Sandbox e-base-stdlib started successfully\n',
                       b' Sandbox e-base-machine started successfully\n',
                       b'Sandbox e-base-machine started successfully extra\n',
                       b'unknown diagnostic\n', b'\n' + self.prefix):
            with self.subTest(prefix=prefix), self.assertRaises(ValueError):
                parse_interface(prefix + self.raw())

    def test_duplicate_keys_rejected_at_top_and_nested_levels(self):
        raw = self.raw()
        values = (b'{"model_executed":true,' + raw[1:],
                  raw.replace(b'"returncode": 0', b'"returncode": 1, "returncode": 0', 1))
        for value in values:
            with self.subTest(raw=value), self.assertRaises(ValueError):
                parse_interface(self.prefix + value)

    def test_extra_or_missing_top_level_field_rejected(self):
        original = dict(self.value)
        self.value['secret'] = 'SYNTHETIC_SECRET'
        with self.assertRaises(ValueError) as caught:
            parse_interface(self.raw())
        self.assertNotIn('SYNTHETIC_SECRET', str(caught.exception))
        self.value = original
        del self.value['commands']
        with self.assertRaises(ValueError):
            parse_interface(self.raw())

    def test_false_flags_require_exact_boolean_false(self):
        for field in ('credentials_explicitly_read', 'auth_status_executed', 'model_executed'):
            for value in (True, 0, None, 'false'):
                with self.subTest(field=field, value=value):
                    changed = dict(self.value, **{field: value})
                    with self.assertRaises(ValueError):
                        parse_interface(json.dumps(changed).encode())

    def test_multiple_documents_partial_json_and_invalid_utf8_rejected(self):
        for raw in (self.raw() + self.raw(), b'{', b'[]', b'null', b'\xff', b''):
            with self.subTest(raw_prefix=raw[:12]), self.assertRaises(ValueError):
                parse_interface(raw)


if __name__ == '__main__':
    unittest.main()
