"""One fixed wildcard diagnostic; no resume or production admission."""
import json
import sys
from managed_cli_guard import require_managed_namespace
from mcp_wildcard_lifecycle import ROOT, run_wildcard
from mcp_probe_entry import interruption_cleanup
from validation_dispatch_receipt import _pairs
from validation_snapshot_input import _file


def main(arguments):
    if arguments != ['--once']: raise ValueError('Fixed wildcard action required')
    require_managed_namespace()
    with interruption_cleanup():
        registration = json.loads(_file(ROOT/'sandbox-registry.json',1048576), object_pairs_hook=_pairs)
        result = run_wildcard(registration)
    print(json.dumps(result), flush=True)


if __name__ == '__main__': main(sys.argv[1:])
