"""Exact closed-network recovery receipt binding; no state mutation or authority."""
import hashlib
import json

from sandbox_turn_fence import _reservation
from turn_validation_result import same_json
from validation_dispatch_receipt import _pairs


def expected_record(fence_raw,window_raw,registration,role):
    if (not isinstance(fence_raw,bytes) or not 0<len(fence_raw)<=65536
            or not isinstance(window_raw,bytes) or len(window_raw)>65536):
        raise ValueError('Bounded original recovery evidence required')
    fence=_reservation(fence_raw,role)
    if (fence['migration_epoch']!=registration.get('migration_epoch')
            or fence['sandbox_id']!=registration['roles'][role]['id']):
        raise ValueError('Recovery registration mismatch')
    return dict(schema=1,phase='closed_recovery',role=role,sandbox_id=fence['sandbox_id'],
        migration_epoch=fence['migration_epoch'],operation_id=fence['operation_id'],
        fence_sha256=hashlib.sha256(fence_raw).hexdigest(),
        window_sha256=hashlib.sha256(window_raw).hexdigest(),
        network_denied_after=True,all_vms_stopped=True,automatic_resume=False,
        model_fence_released=False,stop_removed=False)


def validate_recovery(raw,fence_raw,window_raw,registration,role):
    if not isinstance(raw,bytes) or not 0<len(raw)<=65536:
        raise ValueError('Bounded recovery receipt required')
    value=json.loads(raw,object_pairs_hook=_pairs)
    if not same_json(value,expected_record(fence_raw,window_raw,registration,role)):
        raise ValueError('Recovery receipt does not bind current original evidence')
