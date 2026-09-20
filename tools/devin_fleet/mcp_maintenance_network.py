"""Fixed one-shot machine network window; no public CLI or model invocation.

Caller must own the runtime/lease until final VM stop and bound every command
by the yielded remaining budget. This is not production admission. The fixed
reservation survives every failure and is inspected by the runtime restart gate.
"""
from contextlib import contextmanager
import json
import math
import os
import time

from durable import _sync_directory
from managed_cli_guard import require_managed_namespace
from mcp_maintenance_restart import RUN,CATALOG_RUN,DISCOVERY_RUN,WILDCARD_RUN,CONTROL_RUN,MACHINE
from mcp_maintenance_restart import COMPATIBLE_CONTROL_RUN, PARAMS_CONTROL_RUN
from mcp_probe_reservation import _private_directory,_exclusive_file
from model_network_window import _policy_window
from observed_boundary_admission import make_boundary_check
from process_control import global_lock_held
from sandbox_repository import GuestRepository
from sandbox_runtime import SandboxRuntime
from sandbox_turn_fence import _directory
from validation_snapshot_input import _file
from validation_dispatch_receipt import _pairs
from turn_validation_result import same_json

IMAGE='sha256:df7d566115e4d16b23a0477be5677ea0eb569de027bc1933238859a6f62293fd'


@contextmanager
def machine_probe_network(runtime,repo,*,timeout):
    with _reserved_network(runtime,repo,timeout=timeout,run=RUN) as remaining:
        yield remaining


@contextmanager
def discovery_probe_network(runtime,repo,*,timeout):
    with _reserved_network(runtime,repo,timeout=timeout,run=DISCOVERY_RUN) as remaining:
        yield remaining


@contextmanager
def wildcard_probe_network(runtime,repo,*,timeout):
    with _reserved_network(runtime,repo,timeout=timeout,run=WILDCARD_RUN) as remaining:
        yield remaining


@contextmanager
def echo_control_network(runtime,repo,*,timeout):
    with _reserved_network(runtime,repo,timeout=timeout,run=CONTROL_RUN) as remaining:
        yield remaining


@contextmanager
def catalog_diagnostic_network(runtime,repo,*,timeout):
    with _reserved_network(runtime,repo,timeout=timeout,run=CATALOG_RUN) as remaining:
        yield remaining


@contextmanager
def compatible_control_network(runtime,repo,*,timeout):
    with _reserved_network(runtime,repo,timeout=timeout,run=COMPATIBLE_CONTROL_RUN) as remaining:
        yield remaining


@contextmanager
def params_control_network(runtime,repo,*,timeout):
    with _reserved_network(runtime,repo,timeout=timeout,run=PARAMS_CONTROL_RUN) as remaining:
        yield remaining


@contextmanager
def _reserved_network(runtime,repo,*,timeout,run):
    require_managed_namespace()
    if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0<timeout<=300:
        raise ValueError('Bounded maintenance window required')
    if (not isinstance(runtime,SandboxRuntime) or not isinstance(repo,GuestRepository)
            or runtime.registration.get('production_enabled') is not False
            or run not in (RUN,CATALOG_RUN,DISCOVERY_RUN,WILDCARD_RUN,CONTROL_RUN,COMPATIBLE_CONTROL_RUN,PARAMS_CONTROL_RUN)
            or runtime.root!=run.parent or runtime.root.resolve()!=runtime.root
            or not runtime._entered or runtime._failed or runtime.capacity!=1
            or set(runtime._active)!={'machine'}
            or runtime._active['machine'][1] is not repo.controller
            or repo.controller.fenced or repo.controller.sandbox_id!=MACHINE
            or runtime.registration['roles']['machine'].get('id')!=MACHINE
            or runtime.registration['roles']['machine'].get('name')!='e-base-machine'
            or repo.guest_root!='/home/agent/workspace/machine'
            or repo.external_stop!=runtime.stop_path
            or not global_lock_held('/tmp/e-base-devin-fleet-global.lock')
            or os.path.lexists(runtime.stop_path)):
        raise ValueError('Exact locked maintenance machine lease required')
    for parent in run.parents: _directory(parent,private=parent==runtime.root)
    if os.path.lexists(run): raise FileExistsError('Maintenance network attempt already reserved')
    def registration_unchanged():
        current=json.loads(_file(run.parent/'sandbox-registry.json',1048576),object_pairs_hook=_pairs)
        if not same_json(current,runtime.registration): raise ValueError('Maintenance registration changed')
    registration_unchanged()
    started=time.monotonic()
    def remaining():
        seconds=timeout-(time.monotonic()-started)
        if seconds<=0 or os.path.lexists(runtime.stop_path):
            raise RuntimeError('Maintenance window deadline or STOP')
        return seconds
    try:
        boundary=make_boundary_check(IMAGE)
        boundary(runtime,'machine',stage='before_prepare',repo=repo,timeout=remaining())
        registration_unchanged()
        remaining()
        # mkdir is exclusive. A partial run intentionally blocks every new runtime.
        run.mkdir(mode=0o700)
        _sync_directory(run.parent)
        fd=_private_directory(run)
        try:
            record=dict(schema=1,sandbox_id=MACHINE,run_directory=str(run),state='reserved',automatic_resume=False)
            _exclusive_file(fd,'network-attempt.json',json.dumps(record).encode())
            os.fsync(fd)
        finally: os.close(fd)
        # Both fixed diagnostics require the catalog feature endpoint. Production
        # enters through model_network_window and keeps its three-host scope.
        options={'catalog_access':True}
        with _policy_window(runtime,'machine',repo,run/'network-window',timeout=remaining(),**options):
            yield remaining()
            remaining()
    except BaseException:
        runtime._failed=True
        repo.controller.stop()
        raise
