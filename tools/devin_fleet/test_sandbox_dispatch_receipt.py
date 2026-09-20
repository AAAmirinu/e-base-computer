import json
import unittest
from validation_dispatch_receipt import parse_summary

DIGEST, IMAGE, BASE = 'a' * 64, 'sha256:' + 'b' * 64, 'c' * 40


def fixture():
    return {'receipt_path': '/tmp/validation-source-' + 'd' * 32 + '.json', 'receipt': {
        'schema': 1, 'operation': 'd' * 32, 'container_id': 'e' * 64,
        'container_name': 'e-base-check-' + 'd' * 32, 'manifest_sha256': DIGEST,
        'image_id': IMAGE, 'base': BASE, 'phase': 'complete', 'container_stopped': True,
        'validation_passed': False, 'materialization': {'manifest_sha256': DIGEST, 'base': BASE}}}


class DispatchReceiptTests(unittest.TestCase):
    def test_valid_banner_and_summary(self):
        value = fixture()
        self.assertEqual(parse_summary(b'Sandbox started\n' + json.dumps(value).encode(), DIGEST, IMAGE, BASE), value)

    def test_bound_fields(self):
        for field in ('schema', 'operation', 'container_id', 'container_name', 'manifest_sha256', 'image_id', 'base', 'phase', 'container_stopped', 'validation_passed', 'materialization'):
            value = fixture()
            value['receipt'][field] = None
            with self.subTest(field=field), self.assertRaises(ValueError):
                parse_summary(json.dumps(value).encode(), DIGEST, IMAGE, BASE)

    def test_wrong_guest_receipt_path(self):
        value = fixture()
        value['receipt_path'] = '/other'
        with self.assertRaises(ValueError):
            parse_summary(json.dumps(value).encode(), DIGEST, IMAGE, BASE)

    def test_duplicate_and_missing_summaries(self):
        valid = json.dumps(fixture()).encode()
        for raw in (b'', valid + b'\n' + valid, b'{"receipt":{},"receipt":{}}', b'{"receipt":null}'):
            with self.assertRaises(ValueError):
                parse_summary(raw, DIGEST, IMAGE, BASE)


if __name__ == '__main__':
    unittest.main()
