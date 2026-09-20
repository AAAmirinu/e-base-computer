"""Strict free-catalog parsing only; no authentication, network, or model calls."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import unittest

from model_catalog_policy import require_free_model


class ModelCatalogPolicyTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 20, tzinfo=timezone.utc)
        self.variant = {'model_uid': 'swe-2-high', 'cost_tier': 'Free'}
        self.payload = {'families': [{'variants': [dict(self.variant)]}]}

    def raw(self, payload=None):
        return json.dumps(self.payload if payload is None else payload, separators=(',', ':')).encode()

    def invoke(self, raw=None, returncode=0, now=None):
        return require_free_model(self.raw() if raw is None else raw, returncode,
                                  now=self.now if now is None else now)

    def test_exact_free_model_returns_digest_not_authentication_claim(self):
        raw = self.raw()
        result = self.invoke(raw)
        self.assertEqual(result, dict(model_uid='swe-2-high', cost_tier='Free',
            catalog_sha256=hashlib.sha256(raw).hexdigest(), model_executed=False,
            authentication_verified=False))

    def test_unrelated_models_do_not_replace_or_conflict_with_single_target(self):
        self.payload['families'].append({'variants': [
            {'model_uid': 'swe-2-medium', 'cost_tier': 'Paid'},
            {'model_uid': 'other-model', 'cost_tier': 'Free'}]})
        self.assertEqual(self.invoke()['model_uid'], 'swe-2-high')

    def test_target_duplicate_free_free_or_free_paid_is_ambiguous(self):
        for tier in ('Free', 'Paid'):
            for separate in (False, True):
                with self.subTest(tier=tier, separate=separate):
                    duplicate = dict(self.variant, cost_tier=tier)
                    payload = {'families': [{'variants': [dict(self.variant)]}]}
                    if separate:
                        payload['families'].append({'variants': [duplicate]})
                    else:
                        payload['families'][0]['variants'].append(duplicate)
                    with self.assertRaises((ValueError, RuntimeError)):
                        self.invoke(self.raw(payload))

    def test_uid_and_cost_tier_must_match_exactly(self):
        for key, value in (('model_uid', 'SWE-2 High'), ('model_uid', 'swe-2-high '),
                           ('cost_tier', 'free'), ('cost_tier', 'Free '),
                           ('cost_tier', 'Paid'), ('cost_tier', None)):
            with self.subTest(key=key, value=value), self.assertRaises((ValueError, RuntimeError)):
                self.invoke(self.raw({'families': [{'variants': [dict(self.variant, **{key: value})]}]}))

    def test_returncode_requires_exact_integer_zero(self):
        for code in (True, False, 0.0, '0', None, 1, -1):
            with self.subTest(code=code), self.assertRaises((ValueError, RuntimeError)):
                self.invoke(returncode=code)

    def test_campaign_deadline_is_exclusive(self):
        expiry = datetime(2026, 10, 10, tzinfo=timezone.utc)
        self.invoke(now=expiry - timedelta(microseconds=1))
        for now in (expiry, expiry + timedelta(seconds=1)):
            with self.subTest(now=now), self.assertRaises((ValueError, RuntimeError)):
                self.invoke(now=now)

    def test_naive_datetime_rejected(self):
        with self.assertRaises((ValueError, RuntimeError)):
            self.invoke(now=datetime(2026, 9, 20))

    def test_aware_offset_cannot_bypass_utc_deadline(self):
        japan = timezone(timedelta(hours=9))
        self.invoke(now=datetime(2026, 10, 10, 8, 59, 59, tzinfo=japan))
        with self.assertRaises(ValueError):
            self.invoke(now=datetime(2026, 10, 10, 9, 0, 0, tzinfo=japan))

    def test_duplicate_json_keys_rejected_at_every_schema_level(self):
        raw = self.raw()
        variants = (
            b'{"families":[],' + raw[1:],
            raw.replace(b'"variants":', b'"variants":[],"variants":'),
            raw.replace(b'"cost_tier":"Free"', b'"cost_tier":"Paid","cost_tier":"Free"'),
        )
        for value in variants:
            with self.subTest(raw=value), self.assertRaises((ValueError, RuntimeError)):
                self.invoke(value)

    def test_raw_input_must_be_nonempty_bounded_json_bytes(self):
        for raw in (b'', self.raw().decode(), b'{', b'\xff', b'x' * (1024 * 1024 + 1)):
            with self.subTest(kind=type(raw).__name__, size=len(raw)), self.assertRaises((ValueError, RuntimeError)):
                self.invoke(raw)

    def test_malformed_nested_types_are_rejected(self):
        for payload in ([], {'families': None}, {'families': {}}, {'families': [None]},
                        {'families': [{'variants': {}}]}, {'families': [{'variants': None}]},
                        {'families': [{'variants': [None]}]}, {'families': [{'variants': ['Free']}]},
                        {'families': []}):
            with self.subTest(payload=payload), self.assertRaises((ValueError, RuntimeError)):
                self.invoke(self.raw(payload))

    def test_family_limit_boundary(self):
        payload = {'families': [{'variants': [dict(self.variant)]}] + [{'variants': []} for _ in range(255)]}
        self.invoke(self.raw(payload))
        payload['families'].append({'variants': []})
        with self.assertRaises((ValueError, RuntimeError)):
            self.invoke(self.raw(payload))

    def test_total_variant_limit_applies_across_families(self):
        others = [{'model_uid': 'other-' + str(i), 'cost_tier': 'Paid'} for i in range(2047)]
        payload = {'families': [{'variants': [dict(self.variant)] + others[:1000]},
                                {'variants': others[1000:]}]}
        self.invoke(self.raw(payload))
        payload['families'][1]['variants'].append({'model_uid': 'extra', 'cost_tier': 'Free'})
        with self.assertRaises((ValueError, RuntimeError)):
            self.invoke(self.raw(payload))

    def test_nonfinite_json_constants_refused_even_in_unused_fields(self):
        for constant in (b'NaN', b'Infinity', b'-Infinity'):
            with self.subTest(constant=constant), self.assertRaises(ValueError):
                self.invoke(self.raw()[:-1] + b',"extra":' + constant + b'}')

    def test_untrusted_catalog_fields_are_not_returned(self):
        self.payload['private'] = 'SYNTHETIC_SECRET'
        self.payload['families'][0]['variants'][0]['private'] = 'SYNTHETIC_SECRET'
        result = self.invoke()
        self.assertNotIn('SYNTHETIC_SECRET', json.dumps(result))


if __name__ == '__main__':
    unittest.main()
