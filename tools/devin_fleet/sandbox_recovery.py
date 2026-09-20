"""Pure validation of controller-owned session recovery records.

No VM start, filesystem traversal, Git, or session resume occurs here. Candidate
and integration recovery remain separate; callers must not reuse legacy recovery.
"""
from copy import deepcopy
import hashlib
import json
import uuid
from fleet import MODEL_EXPORT_NAMES


class RecoveryRejected(RuntimeError):
    pass


def recover_sessions(state, registration, records):
    """Return a copy with only current-epoch, verified guest session identities.

    records is an explicit iterable of (outer operation receipt, raw export bytes).
    The driver selects files, not the model. Foreign epochs/legacy receipts are
    ignored; malformed records claiming this epoch fail the complete operation.
    """
    epoch = registration['migration_epoch']
    if str(uuid.UUID(epoch)) != epoch or registration.get('backend') != 'sandbox':
        raise RecoveryRejected('Invalid sandbox migration registration')
    roles = registration['roles']
    latest, identities, sequences = {}, set(), set()
    for receipt, raw in records:
        if not isinstance(receipt, dict):
            raise RecoveryRejected('Invalid operation receipt')
        if receipt.get('migration_epoch') != epoch:
            continue
        role = receipt.get('role')
        if role not in roles or receipt.get('kind') != 'sandbox':
            raise RecoveryRejected('Unknown current-epoch operation')
        if (receipt.get('sandbox_id') != roles[role]['id']
                or receipt.get('sandbox_name') != roles[role]['name']):
            raise RecoveryRejected('Sandbox identity changed')
        # An interrupted/prepared operation cannot supply a session identity.
        if receipt.get('phase') == 'prepared':
            continue
        if receipt.get('phase') != 'export_verified':
            raise RecoveryRejected('Unknown operation phase')
        operation = receipt.get('operation_id')
        try:
            if uuid.UUID(operation).hex != operation:
                raise ValueError()
        except (ValueError, TypeError, AttributeError) as exc:
            raise RecoveryRejected('Invalid operation identity') from exc
        if operation in identities:
            raise RecoveryRejected('Duplicate operation receipt')
        identities.add(operation)
        sequence = receipt.get('sequence')
        if type(sequence) is not int or sequence < 0:
            raise RecoveryRejected('Invalid operation sequence')
        if (role, sequence) in sequences:
            raise RecoveryRejected('Ambiguous operation sequence')
        sequences.add((role, sequence))
        if not isinstance(raw, bytes) or len(raw) > 16 * 1024 * 1024:
            raise RecoveryRejected('Invalid export size or type')
        if hashlib.sha256(raw).hexdigest() != receipt.get('export_sha256'):
            raise RecoveryRejected('Export digest mismatch')
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('Duplicate JSON field')
                result[key] = value
            return result
        try:
            export = json.loads(raw, object_pairs_hook=unique)
            session = export['session_id']
            steps = [s for s in export['steps'] if s.get('source') == 'agent']
            if (not isinstance(session, str) or not session.strip()
                    or session != receipt.get('session_id') or not steps
                    or any(s.get('model_name') not in MODEL_EXPORT_NAMES for s in steps)):
                raise ValueError('Model/session mismatch')
        except (ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
            raise RecoveryRejected('Invalid verified export') from exc
        if role in latest and sequence == latest[role][0]:
            raise RecoveryRejected('Ambiguous operation sequence')
        if role not in latest or sequence > latest[role][0]:
            latest[role] = (sequence, session)
    recovered = deepcopy(state)
    recovered['sessions'] = {role: value[1] for role, value in latest.items()}
    return recovered
