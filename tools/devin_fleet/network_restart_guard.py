"""Reject uncertain network journals before production runtime admission.

Read-only: this does not recover a VM, clear a fence, or trust a closed journal
without checking current effective policy. Missing window files are safe only
because opening writes its record first at the exact fence-bound location.
"""
import json
import os
from pathlib import Path

from model_network_admission import check_network
from network_recovery_record import validate_recovery
from sandbox_turn_fence import ROLES, _directory, _reservation
from validation_dispatch_receipt import _pairs
from validation_snapshot_input import _file


def inspect_windows(root,registration):
    root=Path(root)
    if (not root.is_absolute() or root.resolve()!=root
            or registration.get('controller_root')!=str(root)):
        raise ValueError('Registered canonical controller root required')
    for parent in root.parents:
        _directory(parent)
    _directory(root,private=True)
    fences=root/'model-turn-fences'
    if not os.path.lexists(fences):
        return {}
    _directory(fences,private=True)
    # No recursion, arbitrary recorded filename, or unbounded history scanning.
    with os.scandir(fences) as entries:
        names=[]
        for entry in entries:
            names.append(entry.name)
            if len(names)>len(ROLES) or entry.name not in {r+'.json' for r in ROLES}:
                raise ValueError('Unexpected role fence entry')
    observed={}
    for name in sorted(names):
        role=name[:-5]
        fence_raw=_file(fences/name,65536)
        fence=_reservation(fence_raw,role)
        if (fence['migration_epoch']!=registration.get('migration_epoch')
                or fence['sandbox_id']!=registration['roles'][role]['id']):
            raise ValueError('Foreign network recovery reservation')
        run=Path(fence['run_directory'])
        if root not in run.parents or run.resolve()!=run:
            raise ValueError('Reservation escapes controller root')
        for parent in run.parents:
            _directory(parent)
        _directory(run,private=True)
        window=run/'network-window'
        if not os.path.lexists(window):
            observed[role]='not_opened'
            continue
        _directory(window,private=True)
        window_raw=_file(window/'network-window.json',65536)
        recovery=window/'recovery'
        if os.path.lexists(recovery):
            _directory(recovery,private=True)
            validate_recovery(_file(recovery/'recovery.json',65536),fence_raw,window_raw,registration,role)
            observed[role]='recovered_closed'
            continue
        value=json.loads(window_raw,object_pairs_hook=_pairs)
        required={'schema','role','sandbox_id','phase','network_denied_after',
                  'automatic_resume','created_deny_ids'}
        if (not isinstance(value,dict) or not required<=set(value)
                or set(value)-required-{'original_deny_id'}
                or type(value['schema']) is not int or value['schema']!=1
                or value['role']!=role or value['sandbox_id']!=fence['sandbox_id']
                or value['automatic_resume'] is not False
                or value['phase']!='closed' or value['network_denied_after'] is not True
                or not isinstance(value['created_deny_ids'],list)
                or len(value['created_deny_ids'])>32
                or any(not isinstance(i,str) or not i or len(i)>128 for i in value['created_deny_ids'])
                or ('original_deny_id' in value and
                    (not isinstance(value['original_deny_id'],str) or not value['original_deny_id']))):
            raise ValueError('Unclosed or ambiguous network window; recovery required')
        observed[role]='closed'
    return observed


def require_closed_windows(runtime):
    observed=inspect_windows(runtime.root,runtime.registration)
    for role,status in observed.items():
        if status in ('closed','recovered_closed'):
            check_network(runtime,role,stage='initial',repo=None,timeout=45)
    return observed
