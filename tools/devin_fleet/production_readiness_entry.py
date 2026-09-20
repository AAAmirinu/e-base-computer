import json
import sys
from mcp_probe_entry import interruption_cleanup
from production_readiness import check

def main(arguments):
    if arguments!=['--check']:raise ValueError('Fixed readiness action required')
    with interruption_cleanup():result=check()
    print(json.dumps(result),flush=True)

if __name__=='__main__':main(sys.argv[1:])
