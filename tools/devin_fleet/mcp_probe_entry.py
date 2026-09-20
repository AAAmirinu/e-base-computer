"""Fixed supervised one-shot entry. No automatic retry or fleet activation."""
from contextlib import contextmanager
import json
import signal
import sys

from managed_cli_guard import require_managed_namespace
from mcp_probe_lifecycle import run_probe,ROOT
from validation_dispatch_receipt import _pairs
from validation_snapshot_input import _file


@contextmanager
def interruption_cleanup():
    signals=(signal.SIGINT,signal.SIGTERM,signal.SIGHUP)
    previous={sig:signal.getsignal(sig) for sig in signals}
    def interrupted(number,frame):
        # Repeated ordinary cancellation must not interrupt denial/VM cleanup.
        # SIGKILL/power loss are handled by the retained restart journal instead.
        for sig in signals: signal.signal(sig,signal.SIG_IGN)
        raise KeyboardInterrupt('One-shot probe interrupted; cleaning up')
    try:
        for sig in signals: signal.signal(sig,interrupted)
        yield
    finally:
        for sig,handler in previous.items(): signal.signal(sig,handler)


def main(arguments):
    if arguments!=['--once']: raise ValueError('Fixed one-shot action required')
    require_managed_namespace()
    with interruption_cleanup():
        registration=json.loads(_file(ROOT/'sandbox-registry.json',1048576),object_pairs_hook=_pairs)
        result=run_probe(registration)
    print(json.dumps(result),flush=True)


if __name__=='__main__': main(sys.argv[1:])
