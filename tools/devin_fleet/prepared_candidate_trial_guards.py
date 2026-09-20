"""Fixed live guards for the single inert prepared-candidate trial.

The host project is trusted prompt/configuration input only.  The guest Git
repository must already be the exact prepared parent; this module never seeds,
repairs, checks out, or otherwise mutates it.
"""
from contextlib import contextmanager
import hashlib
import math
import time

import fleet
from host_boundary_admission import check_host_boundary
from model_network_admission import check_network
from model_network_window import prepared_trial_catalog_window, close_catalog_access
from model_turn_admission import (make_admission as make_model_admission,
                                  make_prepared_catalog_evidence)
from sandbox_catalog_probe import check_catalog
from observed_boundary_admission import make_boundary_check
import prepared_candidate_trial_state as trial_state
import prepared_trial_project as trial_project
from turn_validation_result import same_json


def _verify_guest_parent(repo, project):
    """Read-only exact-parent precondition, before controller input staging."""
    if repo.guest_root != trial_state.trial_guest_root():
        raise ValueError('Trial guest repository root changed')
    if repo.git('rev-parse', 'HEAD').strip() != project['head']:
        raise ValueError('Trial guest HEAD differs from prepared parent')
    if repo.git('rev-parse', 'HEAD^{tree}').strip() != project['tree']:
        raise ValueError('Trial guest tree differs from prepared parent')
    inventory = repo.git('ls-files', '-z')
    if inventory and not inventory.endswith('\0'):
        raise ValueError('Malformed trial guest inventory')
    paths = inventory[:-1].split('\0') if inventory else []
    if paths != sorted(trial_project.FILES):
        raise ValueError('Trial guest inventory differs from prepared parent')
    if fleet.changes(repo):
        raise ValueError('Trial guest worktree must be clean before the model')
    for path in paths:
        if repo.fingerprint(path) != hashlib.sha256(trial_project.FILES[path]).hexdigest():
            raise ValueError('Trial guest file differs from prepared parent')


def make_guards(registration, role, entry, settings):
    """Return the only model admission/network pair accepted by this trial."""
    project = trial_project.inspect()
    frozen = trial_state.runtime_registration()
    request = project['task_request']
    if (not same_json(registration, frozen) or role != 'machine'
            or not same_json(entry, request['entry'])
            or not same_json(settings, request['settings'])):
        raise ValueError('Exact fixed prepared-trial inputs required')
    pin = registration['roles'][role].get('image_digest')
    catalog_evidence = make_prepared_catalog_evidence(
        trial_state.check_runtime_registration)
    base = make_model_admission(registration, role, entry, settings,
        boundary_check=make_boundary_check(pin,guest_root=trial_state.trial_guest_root()),
        network_check=check_network,
        registration_check=trial_state.check_runtime_registration,
        prepared_catalog_evidence=catalog_evidence)
    active_network_directory = None

    def admission(runtime, requested_role, observed_settings, *, stage, repo,
                  prepared, timeout):
        nonlocal active_network_directory
        if stage == 'before_prepare':
            _verify_guest_parent(repo, project)
        if stage == 'before_model':
            if active_network_directory is None:
                raise RuntimeError('Catalog network window not active')
            catalog_evidence.capture(check_catalog(repo, timeout=timeout))
            close_catalog_access(runtime, role, repo, active_network_directory,
                                 timeout=timeout)
        return base(runtime, requested_role, observed_settings, stage=stage,
                    repo=repo, prepared=prepared, timeout=timeout)

    @contextmanager
    def network_scope(runtime, requested_role, repo, directory, *, timeout):
        nonlocal active_network_directory
        if (requested_role != role or not same_json(runtime.registration, registration)
                or runtime.root != trial_state.CONTROLLER):
            raise ValueError('Trial network scope registration or role changed')
        if (type(timeout) not in (int, float) or not math.isfinite(timeout)
                or timeout <= 0):
            raise ValueError('Finite trial network deadline required')
        started = time.monotonic()
        check_host_boundary(runtime, role, image_digest=pin, timeout=timeout)
        remaining = timeout - (time.monotonic() - started)
        if remaining <= 0:
            raise TimeoutError('Trial network deadline reached before opening')
        with prepared_trial_catalog_window(runtime, role, repo, directory,
                                           timeout=remaining):
            active_network_directory = directory
            try:
                yield
            finally:
                active_network_directory = None

    return {'admission': admission, 'network_scope': network_scope}
