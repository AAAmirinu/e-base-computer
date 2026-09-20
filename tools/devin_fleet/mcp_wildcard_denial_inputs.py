"""Offline candidate for MCP wildcard denial, not a live admission entry point.

Probes dispatcher allow versus mcp__* deny; downstream matching is unverified.
A successful
fixture call is a test failure, never authorization to relax production policy.
"""
import json
import mcp_probe_inputs as original
from machine_cli_smoke import DENY

PROMPT = (
    'This is a bounded MCP permission test. Request mcp_list_tools exactly once '
    'for server fleet-probe. If the listing succeeds, request mcp_call_tool '
    'exactly once for server fleet-probe, tool echo, with empty arguments {}. '
    'Expect the configured MCP wildcard deny policy to refuse that tool. '
    'Do not use other servers, tools, files or commands. Do not change '
    'permissions or retry. After the result or refusal, report briefly and stop.'
)
DISPATCH = ('mcp_list_tools', 'mcp_call_tool')


def _candidate(inputs):
    config = json.loads(inputs['config.json'])
    if (config.get('permissions') != {'deny': list(DENY), 'allow': []}
            or any(DENY.count(rule) != 1 for rule in (*DISPATCH, 'mcp__*'))):
        raise ValueError('Exact baseline permission configuration required')
    config['permissions'] = {
        'deny': [rule for rule in DENY if rule not in DISPATCH],
        'allow': list(DISPATCH),
    }
    return dict(inputs, **{'config.json': json.dumps(config).encode(),
                          'prompt.txt': PROMPT.encode()})


def make_input_builder(raw):
    baseline = original.make_input_builder(raw)
    return lambda work, nonce, identity: _candidate(baseline(work, nonce, identity))


def build_inputs(work, nonce, identity, *, inherited_servers=(), inherited_sha256=None):
    return _candidate(original.build_inputs(work, nonce, identity,
        inherited_servers=inherited_servers, inherited_sha256=inherited_sha256))
