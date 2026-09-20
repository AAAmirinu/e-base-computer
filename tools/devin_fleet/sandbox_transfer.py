"""Mountless committed-object transfer between registered VM repositories.

The outer driver handles bundle bytes only; Git runs exclusively in the VMs.
No merge, checkout, remote configuration, or automatic retry is performed.
"""
import hashlib
import uuid


def transfer_commit(runtime, source_role, target_role, commit):
    roles = runtime.registration['roles']
    if source_role not in roles or target_role not in roles or source_role == target_role:
        raise ValueError('Distinct registered source and target roles required')
    if not isinstance(commit, str) or len(commit) != 40 or any(c not in '0123456789abcdef' for c in commit):
        raise ValueError('Exact commit identity required')
    operation = uuid.uuid4().hex
    bundle_ref = 'refs/fleet-transfers/' + operation
    directory = '.fleet/object-transfer-' + operation
    relative = directory + '/objects.bundle'
    limit = 16 * 1024 * 1024
    with runtime.role(source_role) as source:
        source_head = source.git('rev-parse', 'HEAD').strip()
        if source.git('rev-parse', '--verify', commit + '^{commit}').strip() != commit:
            raise RuntimeError('Source commit identity mismatch')
        source.make_directory(directory)
        path = source.guest_root + '/' + relative
        # Preserve even a detached/unreferenced candidate. Create-only prevents
        # overwriting an existing ref; retain this recovery anchor on failures.
        source.git('update-ref', bundle_ref, commit, '0' * 40)
        source.git('bundle', 'create', path, bundle_ref)
        source.git('bundle', 'verify', path)
        if source.git('bundle', 'list-heads', path, bundle_ref).strip() != commit + ' ' + bundle_ref:
            raise RuntimeError('Bundle advertised commit mismatch')
        payload = source.read_bytes(relative, max_bytes=limit)
        if not payload or source.git('rev-parse', 'HEAD').strip() != source_head:
            raise RuntimeError('Empty bundle or source HEAD changed')
        source_id = source.controller.sandbox_id
    digest = hashlib.sha256(payload).hexdigest()
    with runtime.role(target_role) as target:
        target_head = target.git('rev-parse', 'HEAD').strip()
        target.make_directory(directory)
        target.write_large_bytes(relative, payload)
        if target.sha256(relative, max_bytes=limit) != digest:
            raise RuntimeError('Transferred bundle digest mismatch')
        path = target.guest_root + '/' + relative
        target.git('bundle', 'verify', path)
        target.git('fetch', '--no-tags', '--no-write-fetch-head', path, bundle_ref)
        if target.git('rev-parse', '--verify', commit + '^{commit}').strip() != commit:
            raise RuntimeError('Imported commit identity mismatch')
        if target.git('rev-parse', 'HEAD').strip() != target_head:
            raise RuntimeError('Target HEAD changed during object import')
        target_id = target.controller.sandbox_id
    return {'operation_id': operation, 'commit': commit, 'source_role': source_role,
            'target_role': target_role, 'source_id': source_id, 'target_id': target_id,
            'source_head': source_head, 'target_head': target_head,
            'bundle_sha256': digest, 'bundle_bytes': len(payload), 'relative': relative,
            'bundle_ref': bundle_ref}
