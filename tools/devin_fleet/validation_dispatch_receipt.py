"""Bind a trusted guest-runner summary to the outer dispatch, never auto-resume."""
import json
import re


def _pairs(items):
    value = {}
    for key, item in items:
        if key in value:
            raise ValueError('Duplicate result field')
        value[key] = item
    return value


def parse_summary(raw, digest, image, base):
    if not isinstance(raw, bytes) or len(raw) > 8 * 1024 * 1024:
        raise ValueError('Result exceeds bound')
    results = []
    for line in raw.decode('utf-8', 'strict').splitlines():
        if line.lstrip().startswith('{'):
            results.append(json.loads(line, object_pairs_hook=_pairs))
    if len(results) != 1 or not isinstance(results[0], dict):
        raise ValueError('Missing or ambiguous runner summary')
    envelope = results[0]
    result = envelope.get('receipt')
    if not isinstance(result, dict):
        raise ValueError('Missing receipt')
    operation, container = result.get('operation'), result.get('container_id')
    if (not isinstance(operation, str) or not re.fullmatch('[0-9a-f]{32}', operation) or
            not isinstance(container, str) or not re.fullmatch('[0-9a-f]{64}', container)):
        raise ValueError('Invalid execution identity')
    if (type(result.get('schema')) is not int or result['schema'] != 1 or
            result.get('manifest_sha256') != digest or result.get('image_id') != image or
            result.get('base') != base or result.get('container_name') != 'e-base-check-' + operation or
            envelope.get('receipt_path') != '/tmp/validation-source-' + operation + '.json'):
        raise ValueError('Dispatch/result binding mismatch')
    if result.get('phase') != 'complete' or result.get('container_stopped') is not True:
        raise ValueError('Guest cleanup is incomplete')
    if result.get('validation_passed') is not False:
        raise ValueError('Unexpected production acceptance claim')
    materialization = result.get('materialization')
    if (not isinstance(materialization, dict) or materialization.get('manifest_sha256') != digest or
            materialization.get('base') != base):
        raise ValueError('Materialized source mismatch')
    return envelope
