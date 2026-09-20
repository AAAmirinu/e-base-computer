"""Managed one-turn CLI; no activation, arbitrary paths, resume, or retries."""
import json
import re
import sys
from managed_cli_guard import require_managed_namespace
from mcp_probe_entry import interruption_cleanup
from registered_turn_input import load
from registered_one_turn import run


def main(arguments):
    if (len(arguments) != 2 or arguments[0] != '--once'
            or type(arguments[1]) is not str
            or re.fullmatch('[0-9a-f]{32}',arguments[1]) is None):
        raise ValueError('Exactly one fixed turn identity required')
    require_managed_namespace()
    with interruption_cleanup():
        inputs=load(arguments[1])
        run(**inputs)
    # No model-generated text or unrestricted result fields leave this CLI.
    print(json.dumps({'turn_identity':arguments[1],'invocation_returned':True,
                      'automatic_retry':False,'published':False}),flush=True)


if __name__=='__main__':main(sys.argv[1:])
