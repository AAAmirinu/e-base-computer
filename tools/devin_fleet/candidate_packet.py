"""Bounded inert inputs for checked candidate containers; no execution/admission.

Modules must come from the trusted controller, never a model snapshot. Bundle
object/ref validation remains the inner container's responsibility.
"""
import base64
import hashlib
import json
import re

from snapshot_git_tree import expected_tree
from validation_dispatch_receipt import _pairs

MODULES = {'sandbox_snapshot_receiver', 'snapshot_git_tree', 'container_candidate_commit'}
MAX_PACKET = 32 * 1024 * 1024
MAX_BUNDLE = 16 * 1024 * 1024


def _bundle(value, digest):
    if (not isinstance(value, bytes) or not 0 < len(value) <= MAX_BUNDLE
            or hashlib.sha256(value).hexdigest() != digest):
        raise ValueError('Bounded digest-verified bundle required')


def _encode(value):
    return base64.b64encode(value).decode('ascii')


def _packet(value):
    raw = json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
    if len(raw) > MAX_PACKET:
        raise ValueError('Oversize candidate packet')
    return raw


def prepare_build(raw, digest, blobs, parent_bundle, parent_bundle_sha256, parent_ref, modules):
    expected = expected_tree(raw, digest, blobs)
    _bundle(parent_bundle, parent_bundle_sha256)
    if (not isinstance(parent_ref, str)
            or re.fullmatch(r'refs/heads/[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*', parent_ref) is None):
        raise ValueError('Explicit conservative parent branch ref required')
    if (not isinstance(modules, dict) or set(modules) != MODULES
            or any(not isinstance(code, str) or not 0 < len(code.encode('utf-8')) <= 32768
                   for code in modules.values())):
        raise ValueError('Exact bounded trusted controller modules required')
    packet = _packet(dict(modules=modules, manifest=_encode(raw), digest=digest,
        blobs={key: _encode(value) for key, value in blobs.items()},
        parent_bundle=_encode(parent_bundle), parent_bundle_sha256=parent_bundle_sha256,
        parent_ref=parent_ref))
    return packet, expected


def prepare_import(build_packet, bundle, metadata):
    if not isinstance(build_packet, bytes) or not 0 < len(build_packet) <= MAX_PACKET:
        raise ValueError('Bounded build packet required')
    values = json.loads(build_packet, object_pairs_hook=_pairs)
    keys = {'modules', 'manifest', 'digest', 'blobs', 'parent_bundle',
            'parent_bundle_sha256', 'parent_ref'}
    if not isinstance(values, dict) or set(values) != keys:
        raise ValueError('Original build packet required')
    decode = lambda value: base64.b64decode(value, validate=True)
    _, expected = prepare_build(decode(values['manifest']), values['digest'],
        {key: decode(value) for key, value in values['blobs'].items()},
        decode(values['parent_bundle']), values['parent_bundle_sha256'],
        values['parent_ref'], values['modules'])
    fields = {'commit', 'parent', 'tree', 'manifest_sha256', 'bundle_sha256',
              'bundle_bytes', 'production_accepted', 'published'}
    if (not isinstance(metadata, dict) or set(metadata) != fields
            or not isinstance(metadata.get('commit'), str)
            or re.fullmatch('[0-9a-f]{40}', metadata['commit']) is None
            or metadata.get('parent') != expected['base']
            or metadata.get('tree') != expected['tree']
            or metadata.get('manifest_sha256') != values['digest']
            or metadata.get('production_accepted') is not False
            or metadata.get('published') is not False
            or type(metadata.get('bundle_bytes')) is not int):
        raise ValueError('Candidate metadata does not match snapshot')
    _bundle(bundle, metadata['bundle_sha256'])
    if metadata['bundle_bytes'] != len(bundle):
        raise ValueError('Candidate bundle size mismatch')
    values.update(verify_import=True, candidate_metadata=metadata, candidate_bundle=_encode(bundle))
    return _packet(values)
