"""Outer driver ownership and role-to-VM repository binding.

This owns execution lifetimes, not model/catalog/security admission. Only trusted
maintenance callers may use it until the production cutover gates are completed.
No automatic resume after errors; every lease gets a fresh fenced controller.
"""
from contextlib import contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path
import threading
import uuid

from process_control import GlobalLock
from sandbox_control import LinuxTransport, SandboxController, SandboxError, SandboxFenced
from sandbox_repository import GuestRepository

ROLES = frozenset(('coordinator', 'machine', 'toolchain', 'kernel', 'stdlib',
                  'storage', 'services', 'applications', 'devtools', 'assurance'))


class _LeaseController:
    def __init__(self, controller):
        self._controller = controller
        self._mutex = threading.RLock()
        self._valid = True
        self.name, self.sandbox_id = controller.name, controller.sandbox_id

    def revoke(self):
        with self._mutex:
            self._valid = False

    @property
    def fenced(self):
        return not self._valid or self._controller.fenced

    def execute(self, *args, **kwargs):
        with self._mutex:
            if not self._valid:
                raise SandboxFenced('Repository lease has ended')
        return self._controller.execute(*args, **kwargs)

    def stop(self):
        with self._mutex:
            if self._valid:
                self._controller.stop()


class SandboxRuntime:
    def __init__(self, registration, root, *, capacity=1, transport=None):
        self.registration = deepcopy(registration)
        roles = self.registration.get('roles')
        if (self.registration.get('schema') != 1 or not isinstance(roles, dict)
                or set(roles) != ROLES):
            raise ValueError('Exact ten-role registration required')
        identities = set()
        for role, entry in roles.items():
            if entry.get('name') != 'e-base-' + role:
                raise ValueError('Role/sandbox name mismatch')
            identity = entry.get('id')
            if not isinstance(identity, str) or str(uuid.UUID(identity)) != identity or identity in identities:
                raise ValueError('Unique canonical sandbox identities required')
            identities.add(identity)
        verified = self.registration.get('simultaneous_capacity_verified')
        if type(capacity) is not int or type(verified) is not int or not 1 <= capacity <= verified <= 10:
            raise ValueError('Requested capacity exceeds verified capacity')
        self.root = Path(root)
        if not self.root.is_absolute():
            raise ValueError('Absolute controller-owned root required')
        if self.registration.get('production_enabled') is True and (
                self.registration.get('controller_root') != str(self.root) or '..' in self.root.parts):
            raise ValueError('Production controller root must match trusted registration')
        self.stop_path = self.root / 'STOP'
        self.capacity = capacity
        self.transport = transport if transport is not None else LinuxTransport()
        # All dedicated-Linux callers share one namespace regardless of TMPDIR.
        self._lock = GlobalLock('/tmp/e-base-devin-fleet-global.lock') if os.name != 'nt' else GlobalLock()
        self._mutex = threading.RLock()
        self._active = {}
        self._entered = False
        self._failed = False

    def __enter__(self):
        with self._mutex:
            if self._entered or self._failed:
                raise SandboxError('Runtime already entered or requires recovery')
            self._lock.__enter__()
            try:
                result = self.transport.control(['/usr/bin/sbx', 'ls', '--json'], 30)
                if result.returncode:
                    raise SandboxError('Sandbox inventory unavailable')
                rows = json.loads(result.stdout)['sandboxes']
                if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                    raise SandboxError('Invalid sandbox inventory')
                # The credential-free validator shares this manager and the
                # resource budget, but is not one of the ten model roles.
                # Never take ownership while any unowned VM is active/unknown.
                if any(row.get('status') != 'stopped' for row in rows):
                    raise SandboxError('All sandbox workloads must be stopped before runtime entry')
                for role, entry in self.registration['roles'].items():
                    matches = [row for row in rows if row.get('name') == entry['name']]
                    if (len(matches) != 1 or matches[0].get('id') != entry['id']
                            or matches[0].get('status') != 'stopped'):
                        raise SandboxError('Registered sandbox is missing, replaced or not stopped')
                from mcp_maintenance_restart import require_closed_maintenance
                require_closed_maintenance(self)
                if self.registration.get('production_enabled') is True:
                    from network_restart_guard import require_closed_windows
                    require_closed_windows(self)
                self._entered = True
                return self
            except BaseException:
                self._lock.__exit__(None, None, None)
                raise

    @contextmanager
    def role(self, role):
        with self._mutex:
            if not self._entered or self._failed:
                raise SandboxError('Runtime not entered')
            if os.path.lexists(self.stop_path):
                raise SandboxFenced('Fleet STOP requires operator recovery')
            if role not in ROLES or role in self._active or len(self._active) >= self.capacity:
                raise SandboxError('Role/capacity admission refused')
            entry = self.registration['roles'][role]
            if self.registration.get('production_enabled') is True:
                # A missing journal must not let externally opened networking
                # slip through. Check live policy before any VM resume.
                from model_network_admission import check_network
                try:
                    check_network(self,role,stage='initial',repo=None,timeout=45)
                except BaseException:
                    self._failed = True
                    raise
            operation = uuid.uuid4().hex
            work = self.root / 'operations' / operation
            controller = SandboxController(entry['name'], work / 'STOP',
                sandbox_id=entry['id'], transport=self.transport)
            lease = _LeaseController(controller)
            self._active[role] = (controller, lease)
        try:
            with self._mutex:
                if not self._entered or self._active.get(role) != (controller, lease):
                    raise SandboxFenced('Runtime closed during admission')
                controller.resume()
                if os.path.lexists(self.stop_path):
                    raise SandboxFenced('Fleet STOP arrived during admission')
            yield GuestRepository(lease, '/home/agent/workspace/' + role,
                                  work / 'logs', external_stop=self.stop_path)
        finally:
            with self._mutex:
                if self._active.get(role) == (controller, lease):
                    lease.revoke()
                    try:
                        controller.stop()
                    except BaseException:
                        self._failed = True
                        raise
                    else:
                        self._active.pop(role)

    def __exit__(self, exc_type, exc, tb):
        with self._mutex:
            self._entered = False
            errors = []
            for controller, lease in self._active.values():
                lease.revoke()
                try:
                    controller.stop()
                except BaseException as error:
                    self._failed = True
                    errors.append(error)
            self._active.clear()
            self._lock.__exit__(exc_type, exc, tb)
        if errors:
            raise SandboxError('Runtime shutdown incomplete; inspect VMs') from errors[0]
