"""Fixed compatible echo control adapters; no retries or production admission."""
import json
from guest_mcp_dispatch import encode_support
from guest_mcp_wildcard import make_compatible_control_probe
from guest_mcp_prepare import encode_sources
from mcp_maintenance_network import compatible_control_network
from mcp_probe_lifecycle import ROOT, _lease, _run_probe
from mcp_echo_control_collection import collection
from mcp_compatible_control_source import compose
from validation_dispatch_receipt import _pairs
from validation_snapshot_input import _file


def execute(repo, action, *, timeout, admission=None, stop_raw=None):
    if action not in ('preflight', 'dispatch', 'collect'):
        raise ValueError('Fixed compatible control action required')
    bootstrap = make_compatible_control_probe(compose(
        _file(ROOT/'mcp_echo_control_inputs.py',16384).decode(),
        _file(ROOT/'mcp_fixture_compat.py',16384).decode()),
        *[_file(ROOT/name,16384).decode() for name in (
        'mcp_echo_control_evidence.py',
        'mcp_discovery_evidence.py', 'mcp_result_summary.py',
        'mcp_wildcard_denial_evidence.py')])
    command = ['/usr/bin/python3', '-I', '-c', bootstrap,
        _file(ROOT/'guest_mcp_prepare.py',16384).decode(),
        _file(ROOT/'guest_mcp_inspect.py',16384).decode(), encode_sources(ROOT), encode_support(ROOT),
        _file(ROOT/'guest_mcp_dispatch.py',16384).decode(), action]
    if action == 'dispatch': command.append(admission.decode())
    if action == 'collect': command.extend([stop_raw.decode(), _lease(repo)])
    log = repo.log_dir/('compatible-control-'+action+'.log')
    result = repo.controller.execute(command, cwd='/', log_path=log, timeout=timeout,
        max_log_bytes=16384, external_stop=repo.external_stop)
    if type(result.returncode) is not int or result.returncode != 0:
        raise RuntimeError('Compatible control guest stage failed')
    prefix = 'EBASE_MCP_DISPATCH:'
    lines = [line[len(prefix):] for line in _file(log,16384).decode().splitlines() if line.startswith(prefix)]
    if len(lines) != 1: raise ValueError('Exact compatible control receipt required')
    return json.loads(lines[0], object_pairs_hook=_pairs)


def run_control(registration):
    return _run_probe(registration, execute=execute, network=compatible_control_network,
        collection=collection, evidence_prefix='mcp-compatible-control-lifecycle-')
