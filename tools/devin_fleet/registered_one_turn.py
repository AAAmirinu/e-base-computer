"""Fixed adapter wiring for one registered VM turn; no registration or retry.

Trusted deployment supplies task data and a parent bundle. Callers cannot replace
the runtime, admission, validator or candidate builder through this entry.
"""
from functools import partial
import hashlib
import json

from managed_cli_guard import require_managed_namespace
from sandbox_runtime import SandboxRuntime
from sandbox_one_turn import run_registered_one_turn
from sandbox_validation_adapter import validate
from sandbox_candidate_adapter import build_and_import


def run(*, registration, controller_root, project_root, role, entry, state,
        settings, cycle_directory, sequence, parent_bundle,
        parent_bundle_sha256, parent_ref):
    require_managed_namespace()
    frozen, ownership, options = json.loads(json.dumps(
        [registration, entry, settings], allow_nan=False))
    if type(frozen) is not dict or frozen.get('production_enabled') is not True:
        raise ValueError('Existing production registration required')
    if (type(parent_bundle) is not bytes or not 0 < len(parent_bundle) <= 16*1024*1024
            or type(parent_bundle_sha256) is not str
            or hashlib.sha256(parent_bundle).hexdigest() != parent_bundle_sha256
            or type(parent_ref) is not str or not parent_ref.startswith('refs/heads/')):
        raise ValueError('Explicit bounded parent bundle and branch required')
    # Capacity remains one until a multi-turn scheduler owns parallel lifetimes.
    runtime = partial(SandboxRuntime, frozen, controller_root, capacity=1)
    candidate = partial(build_and_import, registration=frozen,
        parent_bundle=parent_bundle, parent_bundle_sha256=parent_bundle_sha256,
        parent_ref=parent_ref)
    return run_registered_one_turn(registration=frozen, controller_root=controller_root,
        project_root=project_root, role=role, entry=ownership, state=state,
        settings=options, cycle_directory=cycle_directory, sequence=sequence,
        runtime_factory=runtime, validate=validate, build_and_import=candidate)
