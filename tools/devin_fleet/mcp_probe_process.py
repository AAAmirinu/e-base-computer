"""Linux private CLI lifecycle. VM stop remains the descendant-stop boundary.

Trusted supervisor only. No arbitrary model-supplied argv, no raw output capture.
Do not install SIGCHLD auto-reaping or share this child with another waiter.
"""
import math
import os
import signal
import subprocess
import time


def run_private_process(argv, *, cwd, timeout):
    if (type(timeout) not in (int, float) or not math.isfinite(timeout)
            or not 0 < timeout <= 90 or not hasattr(os, 'WNOWAIT')):
        raise ValueError('Linux bounded process execution required')
    if signal.getsignal(signal.SIGCHLD) != signal.SIG_DFL:
        raise ValueError('Exclusive default child reaping required')
    if (type(argv) is not list or not argv or any(type(a) is not str or not a or '\0' in a for a in argv)
            or not os.path.isabs(argv[0])):
        raise ValueError('Trusted absolute command required')
    started = time.monotonic()
    proc = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            close_fds=True, start_new_session=True, umask=0o077)
    timed_out = False
    group_stop_requested = False
    try:
        while True:
            # Keep the leader unreaped until after killpg: its PID/PGID cannot be reused.
            observed = os.waitid(os.P_PID, proc.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
            if observed is not None:
                break
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                timed_out = True
                break
            time.sleep(min(0.05, remaining))
    finally:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
            group_stop_requested = True
        except ProcessLookupError:
            # An exited leader with no other members need not have a live group.
            group_stop_requested = True
        finally:
            proc.wait(timeout=5)
    return dict(returncode=proc.returncode, timed_out=timed_out,
                leader_reaped=True, process_group_stop_requested=group_stop_requested,
                all_descendants_stopped=False, raw_output_suppressed=True)
