"""Prepare one fixed discovery-only attempt. No CLI, VM, or live entry point."""
import json
import mcp_probe_inputs as original
from machine_cli_smoke import DENY

PROMPT=(
    'This is a bounded MCP discovery-only test. Request mcp_list_tools exactly once '
    'for the fixed server fleet-probe. List its available tools only; do not execute '
    'echo or any other tool. Do not use mcp_call_tool, mcp_list_servers, alternate '
    'tools, files, commands, or other servers. Do not change permissions or retry. '
    'After the single listing result or refusal, report it briefly and stop.'
)


def _discovery(inputs):
    config=json.loads(inputs['config.json'])
    if config.get('permissions')!={'deny':list(DENY),'allow':[]} or DENY.count('mcp_list_tools')!=1:
        raise ValueError('Exact baseline permission configuration required')
    config['permissions']={'deny':[rule for rule in DENY if rule!='mcp_list_tools'],
                           'allow':['mcp_list_tools']}
    # All fixture, runner, inherited overrides, audit and git bytes remain exact.
    return dict(inputs,**{'config.json':json.dumps(config).encode(),
                         'prompt.txt':PROMPT.encode()})


def make_input_builder(raw):
    baseline=original.make_input_builder(raw)
    return lambda work,nonce,identity:_discovery(baseline(work,nonce,identity))


def build_inputs(work,nonce,identity,*,inherited_servers=(),inherited_sha256=None):
    return _discovery(original.build_inputs(work,nonce,identity,
                     inherited_servers=inherited_servers,inherited_sha256=inherited_sha256))
