"""Fixed managed entry for prepare/inspect; never activates production."""
import json
import sys
from mcp_probe_entry import interruption_cleanup
from production_registration_prepare import prepare,inspect

def main(arguments):
    if arguments not in (['--prepare'],['--inspect']):
        raise ValueError('Fixed production candidate action required')
    with interruption_cleanup():result=prepare() if arguments==['--prepare'] else inspect()
    print(json.dumps(result),flush=True)

if __name__=='__main__':main(sys.argv[1:])
