"""One fixed harmless echo control; no resume or production admission."""
import json
import sys
from managed_cli_guard import require_managed_namespace
from mcp_echo_control_lifecycle import ROOT, run_control
from mcp_probe_entry import interruption_cleanup
from validation_dispatch_receipt import _pairs
from validation_snapshot_input import _file


def main(arguments):
    if arguments != ['--once']: raise ValueError('Fixed control action required')
    require_managed_namespace()
    with interruption_cleanup():
        registration=json.loads(_file(ROOT/'sandbox-registry.json',1048576),object_pairs_hook=_pairs)
        result=run_control(registration)
    print(json.dumps(result),flush=True)


if __name__=='__main__':main(sys.argv[1:])
