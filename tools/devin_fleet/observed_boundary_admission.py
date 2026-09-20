"""Compose live host/guest observations. Not a hostile-root isolation proof.

Production activation still requires CLI permission and full-turn acceptance.
This callback never runs a model, changes networking, or authorizes production.
"""
import json
import math
import os
from pathlib import Path
import re
import time
import uuid

from guest_boundary_contract import validate_guest_contract
from host_boundary_admission import check_host_boundary
from managed_cli_guard import require_managed_namespace
from sandbox_repository import GuestRepository
from sandbox_runtime import SandboxRuntime, ROLES
from validation_dispatch_receipt import _pairs
from validation_snapshot_input import _file

ROOT = Path('/home/fleet/controller-validation')
PROBE = "import sys,json; scope={'__name__':'probe'}; exec(compile(sys.argv[1],'<trusted-boundary>','exec'),scope); print(sys.argv[2]+json.dumps(scope['collect']()),flush=True)"


def make_boundary_check(image_digest, *, guest_root=None):
    if type(image_digest) is not str or re.fullmatch(r'sha256:[0-9a-f]{64}', image_digest) is None:
        raise ValueError('Explicit immutable image pin required')

    if guest_root is not None:
        from prepared_candidate_trial_state import trial_guest_root
        if guest_root != trial_guest_root():
            raise ValueError('Only the fixed prepared-candidate trial root is allowed')

    def check(runtime, role, *, stage, repo, timeout):
        require_managed_namespace()
        if (not isinstance(runtime, SandboxRuntime) or not runtime._entered or runtime._failed
                or role not in ROLES or stage not in ('initial','before_prepare','before_model','before_inspection')
                or type(timeout) not in (int,float) or not math.isfinite(timeout) or timeout<=0):
            raise ValueError('Active runtime and bounded stage required')
        started=time.monotonic()
        def remaining():
            seconds=timeout-(time.monotonic()-started)
            if seconds<=0 or os.path.lexists(runtime.stop_path):
                raise RuntimeError('Boundary deadline or STOP')
            return seconds
        if stage=='initial':
            if repo is not None:
                raise ValueError('Initial stage must precede guest lease')
            try:
                check_host_boundary(runtime,role,image_digest=image_digest,timeout=remaining())
                remaining()
            except BaseException:
                runtime._failed=True
                raise
            return
        active=runtime._active.get(role)
        expected_root=guest_root if guest_root is not None else '/home/agent/workspace/'+role
        if (not isinstance(repo,GuestRepository) or active is None or active[1] is not repo.controller
                or repo.controller.fenced
                or repo.controller.sandbox_id!=runtime.registration['roles'][role]['id']
                or repo.guest_root!=expected_root
                or repo.external_stop!=runtime.stop_path):
            raise ValueError('Exact active role lease required')
        try:
            check_host_boundary(runtime,role,image_digest=image_digest,timeout=remaining())
            source=_file(ROOT/'guest_boundary_metadata.py',32768).decode('utf-8')
            marker='EBASE_BOUNDARY_'+uuid.uuid4().hex+':'
            log=repo.log_dir/('boundary-'+uuid.uuid4().hex+'.log')
            completed=repo.controller.execute(['/usr/bin/python3','-I','-c',PROBE,source,marker],
                cwd='/',log_path=log,timeout=min(30,remaining()),max_log_bytes=16384,
                external_stop=repo.external_stop)
            if completed.returncode!=0:
                raise RuntimeError('Guest boundary probe failed')
            lines=[line[len(marker):] for line in _file(log,16384).decode('utf-8').splitlines()
                   if line.startswith(marker)]
            if len(lines)!=1:
                raise ValueError('Missing or ambiguous boundary observation')
            validate_guest_contract(json.loads(lines[0],object_pairs_hook=_pairs))
            check_host_boundary(runtime,role,image_digest=image_digest,timeout=remaining())
            remaining()
        except BaseException:
            runtime._failed=True
            repo.controller.stop()
            raise
    return check
