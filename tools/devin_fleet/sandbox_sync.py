"""Journaled VM-only fast-forward synchronization; not divergent lane rework.

Caller owns the runtime lock and a trusted, private absolute journal parent.
Unfinished receipts require inspection, never automatic replay or rollback.
"""
from pathlib import Path
import re
import uuid

from durable import atomic_write_json, _sync_directory
from sandbox_transfer import transfer_commit

OPERATION_MARKERS = ('index.lock', 'HEAD.lock', 'MERGE_HEAD', 'MERGE_AUTOSTASH',
                     'CHERRY_PICK_HEAD', 'REVERT_HEAD', 'rebase-merge',
                     'rebase-apply', 'sequencer', 'BISECT_START')


def _migration_epoch(registration):
    epoch = registration.get('migration_epoch')
    try:
        if registration.get('backend') != 'sandbox' or str(uuid.UUID(epoch)) != epoch:
            raise ValueError()
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError('Canonical sandbox migration epoch required') from exc
    return epoch


def _check_clean(repo, expected):
    # Migrated repositories are standalone clones. Do not interpret external
    # gitfiles/worktrees or remove an interrupted operation's recovery evidence.
    if (repo.path_kind('.git') != 'directory' or
            repo.git('rev-parse', '--absolute-git-dir').strip() != repo.guest_root + '/.git'):
        raise RuntimeError('Standalone guest Git directory required')
    if any(repo.path_kind('.git/' + name) != 'missing' for name in OPERATION_MARKERS):
        raise RuntimeError('Unfinished Git operation or lock requires inspection')
    if repo.git('rev-parse', 'HEAD').strip() != expected:
        raise RuntimeError('Synchronization HEAD changed')
    if repo.git('status', '--porcelain=v1', '-z', '--untracked-files=all'):
        raise RuntimeError('Synchronization requires preserved clean worktree')
    attachment = repo.git('rev-parse', '--symbolic-full-name', 'HEAD').strip()
    if attachment != 'HEAD' and not attachment.startswith('refs/heads/'):
        raise RuntimeError('Unexpected HEAD attachment')
    return attachment


def synchronize_fast_forward(runtime, source_role, target_role, baseline,
                             expected_head, journal_directory):
    epoch = _migration_epoch(runtime.registration)
    roles = runtime.registration['roles']
    if source_role not in roles or target_role not in roles or source_role == target_role:
        raise ValueError('Distinct registered roles required')
    if any(not isinstance(v, str) or re.fullmatch('[0-9a-f]{40}', v) is None
           for v in (baseline, expected_head)):
        raise ValueError('Exact commit identities required')
    directory = Path(journal_directory)
    if not directory.is_absolute():
        raise ValueError('Absolute private journal directory required')
    directory.mkdir(mode=0o700)  # Exclusive attempt: never overwrite old evidence.
    _sync_directory(directory.parent)
    path = directory / 'receipt.json'
    receipt = {'schema': 2, 'migration_epoch': epoch, 'operation_id': uuid.uuid4().hex,
               'phase': 'prepared', 'source_role': source_role,
               'target_role': target_role, 'source_id': roles[source_role]['id'],
               'target_id': roles[target_role]['id'], 'before': expected_head,
               'baseline': baseline}
    atomic_write_json(path, receipt)
    with runtime.role(target_role) as target:
        receipt['head_ref'] = _check_clean(target, expected_head)
        receipt['guest_root'] = target.guest_root
    atomic_write_json(path, receipt)
    if expected_head == baseline:
        receipt.update(phase='complete', no_op=True)
        atomic_write_json(path, receipt)
        return receipt
    receipt['transfer'] = transfer_commit(runtime, source_role, target_role, baseline)
    receipt['phase'] = 'transferred'
    atomic_write_json(path, receipt)
    with runtime.role(target_role) as target:
        if (target.guest_root != receipt['guest_root'] or
                _check_clean(target, expected_head) != receipt['head_ref']):
            raise RuntimeError('Synchronization repository or HEAD attachment changed')
        if target.git('merge-base', expected_head, baseline).strip() != expected_head:
            raise RuntimeError('Divergent history requires separate rework/integration')
        receipt['phase'] = 'applying'
        atomic_write_json(path, receipt)
        target.git('-c', 'core.hooksPath=/dev/null', '-c', 'merge.autoStash=false',
                   'merge', '--ff-only', '--no-edit', '--no-autostash',
                   '--no-overwrite-ignore', baseline)
        if (target.guest_root != receipt['guest_root'] or
                _check_clean(target, baseline) != receipt['head_ref']):
            raise RuntimeError('Synchronization repository or HEAD attachment changed after merge')
    # Lease exit proves the VM stopped before recording successful completion.
    receipt['phase'] = 'complete'
    atomic_write_json(path, receipt)
    return receipt
