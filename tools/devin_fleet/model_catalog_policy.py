"""Exact free-model catalog contract; not authentication or account-capacity proof."""
from datetime import datetime, timezone
import hashlib
import json

MODEL = 'swe-2-high'
EXPIRY = datetime(2026, 10, 10, tzinfo=timezone.utc)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate catalog key')
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError('Non-finite JSON constant refused')


def require_free_model(raw, returncode, *, now):
    if (not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None
            or now >= EXPIRY):
        raise ValueError('Verified unexpired campaign time required')
    if type(returncode) is not int or returncode != 0:
        raise ValueError('Successful catalog command required')
    if not isinstance(raw, bytes) or not 0 < len(raw) <= 1024*1024:
        raise ValueError('Bounded raw catalog bytes required')
    value = json.loads(raw, object_pairs_hook=_unique, parse_constant=_reject_constant)
    if not isinstance(value, dict) or not isinstance(value.get('families'), list):
        raise ValueError('Catalog family list required')
    if not 0 < len(value['families']) <= 256:
        raise ValueError('Catalog family bound exceeded')
    variants = []
    for family in value['families']:
        if not isinstance(family, dict) or not isinstance(family.get('variants'), list):
            raise ValueError('Catalog variant list required')
        variants.extend(family['variants'])
        if len(variants) > 2048 or any(not isinstance(v, dict) for v in family['variants']):
            raise ValueError('Invalid or excessive catalog variants')
    selected = [v for v in variants if v.get('model_uid') == MODEL]
    if len(selected) != 1 or selected[0].get('cost_tier') != 'Free':
        raise ValueError('Exactly one free SWE-2 High entry required; no fallback')
    return dict(model_uid=MODEL, cost_tier='Free', catalog_sha256=hashlib.sha256(raw).hexdigest(),
                model_executed=False, authentication_verified=False)
