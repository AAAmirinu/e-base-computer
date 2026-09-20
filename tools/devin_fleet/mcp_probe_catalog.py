"""Bounded, fresh CLI catalog capture. No model inference or raw output logging."""
import math
import os
import re
import selectors
import signal
import subprocess
import time

CLI='/home/agent/.local/bin/devin-cli'


class CaptureDeadline(TimeoutError):
    """Finite process/pipe observations only; never include CLI output or argv."""
    def __init__(self, *, leader_exited, stdout_bytes, stderr_bytes, open_streams):
        self.observation = dict(leader_exited=leader_exited, stdout_bytes=stdout_bytes,
                                stderr_bytes=stderr_bytes, open_streams=sorted(open_streams))
        super().__init__('Catalog deadline exceeded; leader_exited=%s stdout_bytes=%d '
                         'stderr_bytes=%d open_streams=%s' %
                         (leader_exited, stdout_bytes, stderr_bytes,
                          ','.join(self.observation['open_streams'])))


def _capture(argv, cwd, *, timeout=20, diagnostic=False):
    """Trusted commands only; retain leader until process-group stop is requested."""
    if (type(diagnostic) is not bool or type(timeout) not in (int,float) or not math.isfinite(timeout)
            or not 0<timeout<=(60 if diagnostic else 20)
            or not hasattr(os,'WNOWAIT') or signal.getsignal(signal.SIGCHLD)!=signal.SIG_DFL):
        raise ValueError('Bounded Linux capture required')
    deadline=time.monotonic()+timeout
    selector=selectors.DefaultSelector()
    try:
        proc=subprocess.Popen(argv,cwd=cwd,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                              start_new_session=True,close_fds=True,umask=0o077)
    except BaseException:
        selector.close()
        raise
    stdout=bytearray()
    sizes={'out':0,'err':0}
    exited=False
    try:
        for stream,label in ((proc.stdout,'out'),(proc.stderr,'err')):
            os.set_blocking(stream.fileno(),False)
            selector.register(stream,selectors.EVENT_READ,label)
        while True:
            if not exited and os.waitid(os.P_PID,proc.pid,os.WEXITED|os.WNOHANG|os.WNOWAIT) is not None:
                exited=True
                try: os.killpg(proc.pid,signal.SIGKILL)
                except ProcessLookupError: pass
            if exited and not selector.get_map(): break
            remaining=deadline-time.monotonic()
            if remaining<=0:
                raise CaptureDeadline(leader_exited=exited, stdout_bytes=sizes['out'],
                                      stderr_bytes=sizes['err'],
                                      open_streams=[key.data for key in selector.get_map().values()])
            for key,_ in selector.select(min(.05,remaining)):
                raw=os.read(key.fileobj.fileno(),65536)
                if not raw:
                    selector.unregister(key.fileobj)
                    continue
                sizes[key.data]+=len(raw)
                if sizes[key.data]>(1048576 if key.data=='out' else 65536):
                    raise ValueError('Catalog output limit exceeded')
                if key.data=='out': stdout.extend(raw)
    finally:
        try:
            try: os.killpg(proc.pid,signal.SIGKILL)
            except ProcessLookupError: pass
        finally:
            try: proc.wait(timeout=5)
            finally:
                selector.close()
                proc.stdout.close()
                proc.stderr.close()
    return bytes(stdout),proc.returncode


def read_catalog(work, *, timeout=60):
    work=str(work)
    if re.fullmatch(r'/tmp/e-base-mcp-probe-[a-z0-9_]{8}',work) is None:
        raise ValueError('Fixed reserved work required')
    return _capture([CLI,'--config',work+'/config.json','models','list','--format','json'],work,timeout=timeout,diagnostic=True)
