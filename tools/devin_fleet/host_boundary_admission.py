"""Live manager-side contract check. No mutation, guest start, or auto-pinning."""
import json
import math
import time

from host_boundary_contract import validate_host_contract
from managed_cli_guard import require_managed_namespace
from sandbox_runtime import ROLES
from validation_dispatch_receipt import _pairs


def check_host_boundary(runtime, role, *, image_digest, timeout):
    require_managed_namespace()
    if role not in ROLES or type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('Known role and finite deadline required')
    name = 'e-base-'+role
    if runtime.registration['roles'][role]['name'] != name:
        raise ValueError('Registered role name mismatch')
    started = time.monotonic()

    def query(args, *, boolean=False):
        remaining = timeout-(time.monotonic()-started)
        if remaining <= 0:
            raise TimeoutError('Host boundary deadline')
        response = runtime.transport.control(['/usr/bin/sbx', *args], min(10, remaining))
        if response.returncode != 0 or type(response.stdout) is not str:
            raise RuntimeError('Host boundary query failed')
        if len(response.stdout.encode()) > 1048576:
            raise ValueError('Host boundary response limit')
        if boolean:
            if response.stdout.strip() not in ('false', 'true'):
                raise ValueError('Unrecognized sharing setting')
            return response.stdout.strip() == 'true'
        return json.loads(response.stdout, object_pairs_hook=_pairs)

    # Two observations reject a change during the check without freezing uptime,
    # sessions, or network (network has a separate stage-specific verifier).
    for _ in range(2):
        ssh = query(['settings', 'get', 'ssh.agentForwardingEnabled'], boolean=True)
        clipboard = query(['settings', 'get', 'clipboard.imagePaste'], boolean=True)
        mcp = query(['mcp', 'ls', '--json'])
        value = query(['inspect', name, '--json'])
        validate_host_contract(value, name=name, image_digest=image_digest,
                               ssh_enabled=ssh, clipboard_enabled=clipboard, mcp=mcp)
    if time.monotonic()-started >= timeout:
        raise TimeoutError('Host boundary deadline')
