"""Compute a Git SHA-1 tree from validated snapshot bytes; no Git/source execution.

This is a content binding only, not authorization to commit, resume, or publish.
Compare the result with the final commit's tree, not merely the working tree.
"""
import hashlib

from sandbox_snapshot_receiver import validate_snapshot


def object_id(kind, payload):
    return hashlib.sha1(kind + b' ' + str(len(payload)).encode('ascii') + b'\0' + payload).digest()


def expected_tree(raw, expected_digest, blobs):
    manifest = validate_snapshot(raw, expected_digest, blobs)
    root = {}
    for entry in manifest['files']:
        cursor = root
        parts = entry['path'].split('/')
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[parts[-1]] = (entry['mode'].encode('ascii'), object_id(b'blob', blobs[entry['sha256']]))

    def tree(node):
        ordered = sorted(node, key=lambda name: name.encode('utf-8') +
                         (b'/' if isinstance(node[name], dict) else b''))
        entries = []
        for name in ordered:
            item = node[name]
            mode, oid = (b'40000', tree(item)) if isinstance(item, dict) else item
            entries.append(mode + b' ' + name.encode('utf-8') + b'\0' + oid)
        return object_id(b'tree', b''.join(entries))

    return {'schema': 1, 'object_format': 'sha1', 'tree': tree(root).hex(),
            'manifest_sha256': expected_digest, 'base': manifest['base'],
            'file_count': len(manifest['files']), 'source_executed': False,
            'committed': False, 'production_accepted': False}


def verify_commit_tree(raw, expected_digest, blobs, *, observed_format, observed_tree):
    """Caller obtains metadata from the exact commit, using trusted Git.

Does not validate the parent, author, signature, tests, or bundle provenance.
SHA-256 manifest/blob verification remains mandatory; SHA-1 is Git compatibility.
"""
    binding = expected_tree(raw, expected_digest, blobs)
    if observed_format != 'sha1' or observed_tree != binding['tree']:
        raise ValueError('Commit tree differs from validated snapshot or object format')
    return dict(binding, tree_verified=True)
