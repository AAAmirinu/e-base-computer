"""Offline fixed harmless echo control. Not an operational permission profile."""
import json
import mcp_probe_inputs as original
from machine_cli_smoke import DENY

TOOL = 'mcp__fleet-probe__echo'
DISPATCH = ('mcp_list_tools', 'mcp_call_tool')
PROMPT = (
    'This is a bounded MCP permission test. Request mcp_list_tools exactly once '
    'for server fleet-probe. If the listing succeeds, request mcp_call_tool '
    'exactly once for server fleet-probe, tool echo, with empty arguments {}. '
    'Observe the result without predicting whether permission will be granted. '
    'Do not use other servers, tools, files or commands. Do not change '
    'permissions or retry. After the result or refusal, report briefly and stop.'
)


def _control(inputs):
    config=json.loads(inputs['config.json'])
    if (config.get('permissions')!={'deny':list(DENY),'allow':[]}
            or any(DENY.count(rule)!=1 for rule in (*DISPATCH,'mcp__*'))):
        raise ValueError('Exact baseline permission configuration required')
    config['permissions']={
        'deny':[rule for rule in DENY if rule not in (*DISPATCH,'mcp__*')],
        'allow':[*DISPATCH,TOOL],
    }
    return dict(inputs,**{'config.json':json.dumps(config).encode(),'prompt.txt':PROMPT.encode()})


def make_input_builder(raw):
    baseline=original.make_input_builder(raw)
    return lambda work,nonce,identity:_control(baseline(work,nonce,identity))


def build_inputs(work,nonce,identity,*,inherited_servers=(),inherited_sha256=None):
    return _control(original.build_inputs(work,nonce,identity,
        inherited_servers=inherited_servers,inherited_sha256=inherited_sha256))
