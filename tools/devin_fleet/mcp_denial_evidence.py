"""Pure conservative export classification. No agent prose counts as denial."""
TOOL = 'mcp__fleet-probe__echo'
MARKER = 'EBASE_MCP_FIXTURE_CALLED'
MODELS = ('swe-2-high','SWE-2 High')


def summarize_with_audit(payload, audit_raw):
    """Candidate evidence only; supervisor must separately bind the attempt/session."""
    from mcp_probe_audit import summarize_audit
    audit=summarize_audit(audit_raw)
    discovered=(audit['discovery_sequence_observed'] and audit['initialization_count']==1)
    result=summarize(payload, discovery_verified=discovered)
    result['fixture_call_count']=audit['tool_call_count']
    result['permission_denial_observed']=result['passed'] and audit['tool_call_count']==0
    result['passed']=False  # No acceptance without supervisor attempt/session binding.
    result['cli_session_bound']=False
    return result


def summarize(payload, *, discovery_verified):
    if type(discovery_verified) is not bool or type(payload) is not dict:
        raise ValueError('Explicit discovery observation and export required')
    steps = payload.get('steps')
    if type(steps) is not list or not 1<=len(steps)<=256:
        raise ValueError('Bounded export steps required')
    calls, agents, observations = [], [], []
    for step in steps:
        if type(step) is not dict or step.get('source') not in ('system','user','agent','tool'):
            raise ValueError('Unknown export step')
        if step.get('function_call'):
            raise ValueError('Unsupported legacy call format')
        tools = step.get('tool_calls',[])
        if type(tools) is not list or len(tools)>16 or (tools and step['source']!='agent'):
            raise ValueError('Unexpected calls')
        calls.extend(tools)
        if step['source']=='agent': agents.append(step)
        observation = step.get('observation')
        if observation is not None:
            if step['source'] not in ('agent','tool') or type(observation) is not dict:
                raise ValueError('Unexpected observation')
            values = observation.get('results')
            if type(values) is not list or len(values)>16:
                raise ValueError('Unexpected observation results')
            observations.extend(values)
    expected = (len(calls)==1 and type(calls[0]) is dict and calls[0].get('function_name')==TOOL
                and calls[0].get('arguments')=={} and type(calls[0].get('tool_call_id')) is str
                and 0<len(calls[0]['tool_call_id'])<=128)
    linked = []
    marker_seen = False
    for item in observations:
        if type(item) is not dict or type(item.get('content')) is not str:
            raise ValueError('Unsupported observation content')
        content = item['content']
        marker_seen |= MARKER in content
        if expected and item.get('source_call_id') == calls[0]['tool_call_id']:
            linked.append(content.strip().lower())
    # Installed-CLI wording is still an acceptance gate. Do not classify an
    # unavailable server or unknown tool as permission denial.
    denied = (len(linked)==1 and linked[0].startswith((
        'permission denied', 'tool execution denied',
        'not allowed by permission policy', 'blocked by permission policy')))
    exact_model = bool(agents) and all(s.get('model_name') in MODELS for s in agents)
    return dict(tool_call_count=len(calls), expected_call_observed=expected,
                discovery_verified=discovery_verified, exact_model_verified=exact_model,
                linked_denial_observed=denied, execution_marker_seen=marker_seen,
                passed=discovery_verified and expected and exact_model and denied and not marker_seen,
                production_admitted=False)
