"""Fail-closed Linux sbx transport, not an isolation/policy attestation.

One controller owns one existing sandbox. The fleet must hold its cross-process
GlobalLock and must not run another controller/CLI against that sandbox. Guest
argv is passed only to sbx exec, never to a host shell. This module neither copies
credentials nor provisions/starts a model. A new controller starts fenced even
when STOP is absent; explicit resume verifies a stopped sandbox first.
Use a private per-sandbox stop_path, not the fleet-wide STOP: resume clears only
this controller's fence. The fleet-wide admission barrier remains the caller's
responsibility. Host log/control paths must be trusted, not guest-provided.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import signal
import subprocess
import sys
import threading
import time
import uuid

from durable import _atomic_bytes, _sync_directory
from managed_cli_guard import require_managed_namespace


class SandboxError(RuntimeError):
    pass


class SandboxFenced(SandboxError):
    pass


def _positive(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError("timeout must be finite and positive")
    return value


class LinuxTransport:
    """Only spawn the installed sbx client; kill only handles created here."""

    def __init__(self):
        if sys.platform != "linux":
            raise SandboxError("Native Linux host required; no Windows/host fallback")

    @staticmethod
    def _environment():
        env = os.environ.copy()
        for key in ("DISPLAY", "WAYLAND_DISPLAY", "PULSE_SERVER", "SSH_AUTH_SOCK",
                    "SSH_AGENT_PID", "DBUS_SESSION_BUS_ADDRESS"):
            env.pop(key, None)
        return env

    def spawn(self, argv, log):
        require_managed_namespace()
        return subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=log,
                                stderr=subprocess.STDOUT, start_new_session=True,
                                env=self._environment())

    def cancel(self, proc, timeout):
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        proc.wait(timeout=timeout)

    def control(self, argv, timeout):
        # communicate drains both pipes. No subprocess.run timeout orphan: the
        # complete owned process group is reaped before returning/raising.
        require_managed_namespace()
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, start_new_session=True, text=True,
                                env=self._environment())
        try:
            out, err = proc.communicate(timeout=timeout)
        except BaseException:
            self.cancel(proc, 5)
            raise
        return subprocess.CompletedProcess(argv, proc.returncode, out, err)


class SandboxController:
    def __init__(self, name, stop_path, *, sandbox_id, sbx="/usr/bin/sbx", transport=None,
                 control_timeout=30):
        if not isinstance(name, str) or not re.fullmatch(r"e-base-[a-z0-9]+(?:-[a-z0-9]+)*", name):
            raise ValueError("Explicit e-base-* sandbox name required")
        if not isinstance(sbx, str) or not PurePosixPath(sbx).is_absolute() or "\x00" in sbx:
            raise ValueError("Absolute trusted Linux sbx executable required")
        if not isinstance(sandbox_id, str) or str(uuid.UUID(sandbox_id)) != sandbox_id:
            raise ValueError("Canonical recorded sandbox UUID required")
        self.name, self.stop_path, self.sbx = name, Path(stop_path), sbx
        self.sandbox_id = sandbox_id
        self.transport = transport if transport is not None else LinuxTransport()
        self.control_timeout = _positive(control_timeout)
        self._admission = threading.Lock()
        self._lifecycle = threading.Lock()
        self._fence = threading.Event()
        self._fence.set()
        self._clients = set()
        self._generation = 0
        self._stop_requests = 0
        self._requests_lock = threading.Lock()

    @property
    def fenced(self):
        return self._fence.is_set() or self.stop_path.exists()

    def _control(self, *args):
        result = self.transport.control([self.sbx, *args], self.control_timeout)
        if result.returncode:
            raise SandboxError("sbx control failed: " + args[0])
        return result

    def _verify_identity(self, *, stopped=False):
        try:
            data = json.loads(self._control("ls", "--json").stdout)
            rows = data["sandboxes"]
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise ValueError("Invalid sandbox list")
            matches = [row for row in rows if row.get("name") == self.name]
            if len(matches) != 1 or matches[0].get("id") != self.sandbox_id:
                raise ValueError("Sandbox identity changed or is missing")
            if matches[0].get("status") not in ("running", "stopped"):
                raise ValueError("Unknown sandbox lifecycle state")
            if stopped and matches[0].get("status") != "stopped":
                raise ValueError("Exact sandbox is not demonstrably stopped")
        except (ValueError, TypeError, KeyError) as exc:
            raise SandboxError("Cannot verify recorded sandbox identity/state") from exc

    def _verify_stopped(self):
        self._verify_identity(stopped=True)

    def resume(self):
        """Explicit operator action, not automatic recovery or model admission."""
        with self._lifecycle, self._admission:
            with self._requests_lock:
                if self._stop_requests:
                    raise SandboxFenced("Stop request is pending")
            if self._clients:
                raise SandboxError("Owned clients remain; stop and inspect first")
            self._fence.set()
            self._verify_stopped()
            if self.stop_path.exists():
                self.stop_path.unlink()
                _sync_directory(self.stop_path.parent)
            with self._requests_lock:
                if self._stop_requests:
                    raise SandboxFenced("Stop request arrived during resume")
                self._generation += 1
                self._fence.clear()

    def stop(self):
        """Fence queued calls, drain clients, stop VM, require live evidence.

        Client termination alone never proves guest termination. Even when client
        draining or STOP persistence fails, still attempt VM stop; errors keep
        the in-memory fence raised and forbid automatic resume.
        """
        with self._requests_lock:
            self._stop_requests += 1
            self._fence.set()  # Reject callers queued behind an in-flight spawn.
        errors = []
        with self._lifecycle:
            with self._admission:
                self._fence.set()  # A concurrent explicit resume may have ended.
                self._generation += 1
                try:
                    _atomic_bytes(self.stop_path, b"sandbox controller STOP\n")
                except Exception as exc:
                    errors.append(exc)
                clients = list(self._clients)
            for proc in clients:
                try:
                    self.transport.cancel(proc, self.control_timeout)
                    if proc.poll() is None:
                        raise SandboxError("Owned client did not terminate")
                    with self._admission:
                        self._clients.discard(proc)
                except Exception as exc:
                    errors.append(exc)
            try:
                # Never stop a replacement that happens to reuse our name.
                self._verify_identity()
                self._control("stop", self.name)
                self._verify_stopped()
            except Exception as exc:
                errors.append(exc)
            with self._requests_lock:
                self._stop_requests -= 1
        if errors:
            raise SandboxError("Stop incomplete; controller remains fenced") from errors[0]

    def execute(self, argv, *, cwd, log_path, timeout, max_log_bytes=16 * 1024 * 1024,
                external_stop=None):
        """Run guest command. Timeout/STOP fences all clients and stops this VM.

        Command timeout excludes bounded stop cleanup; cleanup can take one
        control_timeout per live client plus stop and verification calls.
        """
        _positive(timeout)
        if external_stop is not None:
            external_stop = Path(external_stop)
            if not external_stop.is_absolute() or external_stop == self.stop_path:
                raise ValueError('Distinct absolute fleet STOP path required')
        def stopped():
            # The fleet owns this marker. Never remove it in resume/cleanup.
            return self.fenced or (external_stop is not None and external_stop.exists())
        if type(max_log_bytes) is not int or max_log_bytes <= 0:
            raise ValueError("Positive integer log limit required")
        if not isinstance(argv, (list, tuple)) or not argv or any(
                not isinstance(arg, str) or "\x00" in arg for arg in argv) or not argv[0] or argv[0].startswith("-"):
            raise ValueError("Nonempty guest argument vector required")
        if not isinstance(cwd, str) or not PurePosixPath(cwd).is_absolute() or "\x00" in cwd:
            raise ValueError("Absolute guest working directory required")
        command = [self.sbx, "exec", "-w", cwd, self.name, *argv]
        log_path = Path(log_path)
        proc = None
        admitted = False
        queued_generation = self._generation
        started = time.monotonic()
        try:
            with self._admission:
                if stopped() or queued_generation != self._generation:
                    self._fence.set()
                    raise SandboxFenced("STOP fence requires explicit resume")
                if time.monotonic() - started >= timeout:
                    raise SandboxFenced("Admission deadline expired; no command spawned")
                generation = self._generation
                admitted = True
                self._verify_identity()
                if stopped() or time.monotonic() - started >= timeout:
                    raise SandboxFenced("Stopped or timed out during identity verification")
                log_path.parent.mkdir(parents=True, exist_ok=True)
                with log_path.open("xb") as log:
                    proc = self.transport.spawn(command, log)
                    self._clients.add(proc)
            while True:
                # Polling bounds accepted output, not instantaneous disk usage:
                # a fast writer can overshoot between checks. Never parse it.
                if log_path.stat().st_size > max_log_bytes:
                    raise SandboxFenced("Sandbox log limit exceeded")
                if stopped() or generation != self._generation:
                    raise SandboxFenced("Sandbox execution stopped")
                if time.monotonic() - started >= timeout:
                    raise SandboxFenced("Sandbox execution timed out")
                result = proc.poll()
                if result is not None:
                    return subprocess.CompletedProcess(command, result, "", "")
                time.sleep(0.02)
        except BaseException:
            # Even a failed client spawn cannot be treated as guest termination.
            # Calls rejected before admission do not needlessly stop a resumed VM.
            if admitted:
                self.stop()
            raise
        finally:
            if proc is not None:
                with self._admission:
                    if proc.poll() is not None:
                        self._clients.discard(proc)
