"""Crash-released runner lock and interruptible, runner-owned process execution.

These controls manage liveness. They do not sandbox the invoked program.
"""
from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time


class LockUnavailable(RuntimeError):
    """Another process owns the fleet lock."""


class GlobalLock:
    """Nonblocking advisory lock; kernel releases ownership when a process dies."""

    def __init__(self, path=None):
        self.path = Path(path) if path is not None else Path(tempfile.gettempdir()) / "e-base-devin-fleet-global.lock"
        self._file = None

    def __enter__(self):
        if self._file is not None:
            raise RuntimeError("GlobalLock is already acquired")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                # Windows allows locking a region beyond EOF; do not write into
                # another runner's locked byte before trying to acquire it.
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            if isinstance(exc, (BlockingIOError, PermissionError)) or exc.errno in (11, 13, 35, 36):
                raise LockUnavailable(f"Fleet lock is held: {self.path}") from exc
            raise
        self._file = handle
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        handle, self._file = self._file, None
        if handle is not None:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()


def global_lock_held(path=None):
    """Probe actual lock ownership, not saved PID or leftover lock-file presence."""
    try:
        with GlobalLock(path):
            return False
    except LockUnavailable:
        return True


class RunInterrupted(RuntimeError):
    """A runner-owned command was stopped or exceeded its wall-clock deadline."""

    def __init__(self, reason, argv, log_path):
        self.reason = reason
        self.argv = [str(arg) for arg in argv]
        self.log_path = Path(log_path)
        super().__init__(f"Command {reason}; process tree stopped; log: {self.log_path}")


def _stop_owned_tree(proc):
    # Never accept a stored/arbitrary PID. Only act on the Popen created here,
    # while it is still alive, so a stale process.json cannot kill another task.
    if proc.poll() is not None:
        return
    if os.name == "nt":
        result = subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=20, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode and proc.poll() is None:
            raise RuntimeError(f"Could not stop owned process tree {proc.pid}: "
                               + result.stdout.decode("utf-8", errors="replace")[-1000:])
    else:
        # Each supervised command starts a fresh session; its PGID is its PID.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    proc.wait(timeout=20)


def supervised_run(argv, cwd, log_path, stop_path, timeout, on_start=None):
    """Execute without output pipes; interrupt the owned tree on STOP/timeout.

    Normal nonzero exits are returned, not raised. Logs are preserved on all
    paths. The caller chooses whether a nonzero exit is an error or test result.
    """
    argv = [str(arg) for arg in argv]
    log_path = Path(log_path)
    stop_path = Path(stop_path) if stop_path is not None else None
    if timeout is None or timeout <= 0:
        raise ValueError("timeout must be positive")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if stop_path is not None and stop_path.exists():
        raise RunInterrupted("stop", argv, log_path)
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
    with log_path.open("wb") as log:
        start = time.monotonic()
        proc = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL,
                                stdout=log, stderr=subprocess.STDOUT, **flags)
        stopping_attempted = False
        try:
            if on_start is not None:
                on_start(proc)
            while proc.poll() is None:
                reason = "stop" if stop_path is not None and stop_path.exists() else None
                if reason is None and time.monotonic() - start >= timeout:
                    reason = "timeout"
                if reason is not None:
                    stopping_attempted = True
                    _stop_owned_tree(proc)
                    raise RunInterrupted(reason, argv, log_path)
                time.sleep(0.1)
        except BaseException:
            if not stopping_attempted:
                _stop_owned_tree(proc)
            raise
    return subprocess.CompletedProcess(argv, proc.returncode,
        log_path.read_text(encoding="utf-8", errors="replace"), "")
