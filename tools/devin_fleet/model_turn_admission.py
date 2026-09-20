"""Compose fail-closed single-turn checks; no CLI activation or network mutation.

Boundary/network verifiers are mandatory trusted controller functions, not model
callbacks or boolean evidence files. Their production implementations remain an
activation prerequisite. Construct one callback per turn while holding the lock.
Verifiers return None after successful checks and raise on failure; unexpected
return values (including False) are rejected, never interpreted as acceptance.
"""
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time

import fleet
from candidate_turn_admission import ROOT, IMAGE
from managed_cli_guard import require_managed_namespace
from model_catalog_policy import EXPIRY
from process_control import global_lock_held
from sandbox_catalog_probe import check_catalog
from sandbox_repository import GuestRepository
from sandbox_runtime import SandboxRuntime
from sandbox_turn_fence import ROLES, _directory, _reservation
from turn_validation_result import same_json
from validation_dispatch_receipt import _pairs
from validation_snapshot_input import _file

STAGES=('initial','before_prepare','before_model','before_inspection')


class _PreparedCatalogEvidence:
    def __init__(self):
        self.value = None
        self.consumed = False

    def capture(self, value):
        if self.value is not None or self.consumed or not isinstance(value, dict):
            raise ValueError('Fresh prepared catalog evidence required')
        self.value = json.loads(json.dumps(value, allow_nan=False))

    def consume(self):
        if self.value is None or self.consumed:
            raise ValueError('Prepared catalog evidence missing or reused')
        self.consumed = True
        return json.loads(json.dumps(self.value, allow_nan=False))


def make_prepared_catalog_evidence(registration_check):
    from prepared_candidate_trial_state import check_runtime_registration
    if registration_check is not check_runtime_registration:
        raise ValueError('Exact prepared trial checker required')
    return _PreparedCatalogEvidence()


def make_admission(registration, role, entry, settings, *, boundary_check, network_check,
                   registration_check=None, prepared_catalog_evidence=None):
    if registration_check is not None:
        from prepared_candidate_trial_state import check_runtime_registration
        if registration_check is not check_runtime_registration:
            raise ValueError('Only the fixed prepared-candidate trial checker is allowed')
    if (not callable(boundary_check) or not callable(network_check)
            or (registration_check is not None and not callable(registration_check))):
        raise ValueError('Explicit live boundary and network verifiers required')
    if prepared_catalog_evidence is not None:
        if registration_check is None or not isinstance(prepared_catalog_evidence,
                                                         _PreparedCatalogEvidence):
            raise ValueError('Prepared catalog evidence requires exact trial binding')
    registration,entry,settings=json.loads(json.dumps([registration,entry,settings],allow_nan=False))
    if (role not in ROLES or not isinstance(registration,dict)
            or registration.get('production_enabled') is not True
            or registration.get('validation_image_id')!=IMAGE
            or not isinstance(registration.get('controller_root'),str)
            or role not in registration.get('roles',{})):
        raise ValueError('Explicit production registration required')
    root=Path(registration['controller_root'])
    if not root.is_absolute() or root.resolve()!=root or ROOT not in root.parents:
        raise ValueError('Private production root under controller required')
    index=0
    frozen_fence=None
    failed=False

    def admit(runtime, requested_role, observed_settings, *, stage, repo, prepared, timeout):
        nonlocal index,frozen_fence,failed
        # A failing or repeated callback can never become an implicit retry.
        if failed or index>=len(STAGES) or stage!=STAGES[index]:
            failed=True
            raise RuntimeError('Admission sequence is closed or out of order')
        failed=True
        started=time.monotonic()
        def remaining():
            if type(timeout) not in (int,float) or not math.isfinite(timeout) or timeout<=0:
                raise ValueError('Finite remaining turn time required')
            seconds=min(timeout-(time.monotonic()-started),
                        (EXPIRY-datetime.now(timezone.utc)).total_seconds())
            if seconds<=0 or os.path.lexists(root/'STOP'):
                raise RuntimeError('Admission deadline or STOP')
            return seconds
        remaining()
        require_managed_namespace()
        if (not global_lock_held('/tmp/e-base-devin-fleet-global.lock')
                or not isinstance(runtime,SandboxRuntime) or not runtime._entered
                or runtime._failed or requested_role!=role
                or not same_json(runtime.registration,registration)
                or not same_json(observed_settings,settings)
                or runtime.root!=root or runtime.stop_path!=root/'STOP'
                or type(runtime.capacity) is not int
                or not 1<=runtime.capacity<=registration['simultaneous_capacity_verified']):
            raise ValueError('Current locked runtime and frozen settings required')
        for parent in root.parents:
            _directory(parent)
        _directory(ROOT,private=True)
        _directory(root,private=True)
        if registration_check is None:
            current=json.loads(_file(ROOT/'sandbox-registry.json',65536),object_pairs_hook=_pairs)
            if not same_json(current,registration):
                raise ValueError('Production registration changed')
        elif registration_check(registration) is not None:
            raise ValueError('Trial registration checker must return no value')
        fences=root/'model-turn-fences'
        _directory(fences,private=True)
        raw=_file(fences/(role+'.json'),65536)
        reservation=_reservation(raw,role)
        run=Path(reservation['run_directory'])
        if (reservation['migration_epoch']!=registration.get('migration_epoch')
                or reservation['sandbox_id']!=registration['roles'][role]['id']
                or root not in run.parents or run.resolve()!=run
                or (frozen_fence is not None and frozen_fence!=raw)):
            raise ValueError('Exact unresolved role reservation required')
        for parent in run.parents:
            _directory(parent)
        _directory(run,private=True)
        if stage=='initial':
            if repo is not None or prepared is not None:
                raise ValueError('Initial admission must precede guest access')
        else:
            active=runtime._active.get(role)
            expected_guest_root='/home/agent/workspace/'+role
            if registration_check is not None:
                from prepared_candidate_trial_state import trial_guest_root
                expected_guest_root=trial_guest_root()
            if (not isinstance(repo,GuestRepository) or active is None
                    or repo.controller is not active[1] or repo.controller.fenced
                    or repo.controller.sandbox_id!=registration['roles'][role]['id']
                    or repo.guest_root!=expected_guest_root
                    or repo.external_stop!=runtime.stop_path):
                raise ValueError('Exact active role lease required')
            if stage!='before_model' and prepared is not None:
                raise ValueError('Unexpected model inputs for this stage')
        if boundary_check(runtime,role,stage=stage,repo=repo,timeout=remaining()) is not None:
            raise ValueError('Boundary verifier must complete without a return value')
        if network_check(runtime,role,stage=stage,repo=repo,timeout=remaining()) is not None:
            raise ValueError('Network verifier must complete without a return value')
        result={'stage':stage,'authentication_verified':False,'model_executed':False}
        if stage=='before_model':
            if not isinstance(prepared,dict) or prepared.get('role')!=role:
                raise ValueError('Prepared role inputs required')
            relative=prepared.get('relative')
            if not isinstance(relative,str) or re.fullmatch(r'\.fleet/control-[0-9a-f]{32}',relative) is None:
                raise ValueError('Fresh fixed input directory required')
            policy=repo.read_bytes(relative+'/config.json',max_bytes=32768)
            fleet.verify_guest_file_tool_policy(policy,prepared.get('config_sha256'))
            expected=fleet.guest_permission_config(repo.guest_root,entry)
            if not same_json(json.loads(policy,object_pairs_hook=_pairs),expected):
                raise ValueError('Guest permissions differ from trusted role ownership')
            prompt=repo.read_bytes(relative+'/prompt.md',max_bytes=32768)
            if hashlib.sha256(prompt).hexdigest()!=prepared.get('prompt_sha256'):
                raise ValueError('Prepared prompt changed')
            result['catalog']=(prepared_catalog_evidence.consume()
                if prepared_catalog_evidence is not None else check_catalog(repo,timeout=remaining()))
        remaining()
        frozen_fence=raw
        index+=1
        failed=False
        return result

    return admit
