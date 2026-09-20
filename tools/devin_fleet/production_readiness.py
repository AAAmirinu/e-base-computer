"""Read-only live checks for a prepared candidate; never activate or start a model."""
import json
from pathlib import Path

from host_boundary_admission import check_host_boundary
from managed_cli_guard import require_managed_namespace
from model_network_admission import check_network
from production_registration_prepare import inspect, RUN
from production_role_authentication import inspect as inspect_role_authentication
from production_normal_permission import inspect as inspect_normal_permission
from prepared_trial_full_turn import inspect as inspect_full_turn
from physical_reboot_evidence import inspect as inspect_physical_reboot
from sandbox_runtime import SandboxRuntime, ROLES
from validation_dispatch_receipt import _pairs
from validation_snapshot_input import _file
from turn_validation_result import same_json


def check():
    require_managed_namespace()
    prepared=inspect()
    candidate_raw=_file(RUN/'candidate.json',65536)
    candidate=json.loads(candidate_raw,object_pairs_hook=_pairs)
    root=Path(candidate['controller_root'])
    full_turn_before=inspect_full_turn()
    observed={}
    with SandboxRuntime(candidate,root,capacity=1) as runtime:
        for role in sorted(ROLES):
            check_network(runtime,role,stage='initial',repo=None,timeout=45)
            check_host_boundary(runtime,role,
                image_digest=candidate['roles'][role]['image_digest'],timeout=30)
            observed[role]={'network_denied':True,'host_boundary_verified':True}
    if _file(RUN/'candidate.json',65536)!=candidate_raw or inspect()!=prepared:
        raise ValueError('Prepared candidate changed during readiness check')
    authentication=inspect_role_authentication(candidate,prepared['candidate_sha256'])
    normal_permission=inspect_normal_permission(candidate,prepared['candidate_sha256'])
    full_turn=inspect_full_turn()
    physical_reboot=inspect_physical_reboot()
    # These blockers require separate live evidence; absence is not inferred from
    # a clean host/network check and cannot be auto-approved here.
    if (not same_json(full_turn_before, full_turn)
            or full_turn.get('verified') is not True
            or full_turn.get('candidate_sha256') != prepared['candidate_sha256']
            or full_turn.get('migration_epoch') != prepared['migration_epoch']
            or full_turn.get('activated') is not False
            or full_turn.get('published') is not False):
        raise ValueError('Exact non-activating full-turn evidence required')
    if (physical_reboot.get('verified') is not True
            or physical_reboot.get('candidate_sha256') != prepared['candidate_sha256']
            or physical_reboot.get('all_vms_stopped') is not True
            or physical_reboot.get('automatic_resume') is not False
            or physical_reboot.get('activated') is not False
            or physical_reboot.get('published') is not False):
        raise ValueError('Exact physical reboot evidence required')
    blockers=[]
    return {'schema':1,'phase':'complete','candidate_sha256':prepared['candidate_sha256'],
        'role_count':len(observed),'roles':observed,'all_vms_stopped':True,
        'network_changed':False,'model_executed':False,'activated':False,
        'role_authentication':authentication,'normal_permission_turn':normal_permission,
        'full_turn':full_turn,'physical_reboot':physical_reboot,
        'activation_ready':True,'blockers':blockers}
