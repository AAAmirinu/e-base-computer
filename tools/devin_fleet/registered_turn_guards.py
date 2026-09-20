"""Bind existing live guards to one explicitly registered production turn.

Construction never changes registration, opens a network window, or starts a VM.
CLI permission acceptance and production registration remain operator gates.
"""
from contextlib import contextmanager
import json
import re

from host_boundary_admission import check_host_boundary
from model_network_admission import check_network
from model_network_window import model_network_window
from model_turn_admission import make_admission
from observed_boundary_admission import make_boundary_check
from sandbox_runtime import ROLES
from turn_validation_result import same_json


def make_registered_turn_guards(registration, role, entry, settings):
    frozen, ownership, options = json.loads(json.dumps([registration, entry, settings], allow_nan=False))
    if (type(frozen) is not dict or frozen.get('production_enabled') is not True
            or role not in ROLES or role not in frozen.get('roles', {})):
        raise ValueError('Explicit production role registration required')
    pin = frozen['roles'][role].get('image_digest')
    if type(pin) is not str or re.fullmatch(r'sha256:[0-9a-f]{64}', pin) is None:
        raise ValueError('Role image digest must already be pinned in registration')
    admission = make_admission(frozen, role, ownership, options,
        boundary_check=make_boundary_check(pin), network_check=check_network)

    @contextmanager
    def network_scope(runtime, requested_role, repo, directory, *, timeout):
        if requested_role != role or not same_json(runtime.registration, frozen):
            raise ValueError('Network scope registration or role changed')
        # Opening is a separate side effect from admission. Recheck host sharing
        # before that side effect, not only after the model window has opened.
        import math
        import time
        if type(timeout) not in (int,float) or not math.isfinite(timeout) or timeout<=0:
            raise ValueError('Finite network scope deadline required')
        started=time.monotonic()
        check_host_boundary(runtime, role, image_digest=pin, timeout=timeout)
        remaining=timeout-(time.monotonic()-started)
        if remaining<=0:
            raise TimeoutError('Network scope deadline reached before opening')
        with model_network_window(runtime, role, repo, directory, timeout=remaining):
            yield

    return {'admission': admission, 'network_scope': network_scope}
