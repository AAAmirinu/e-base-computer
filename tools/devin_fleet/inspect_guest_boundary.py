"""Fixed machine metadata maintenance probe; no model or permission changes."""
import json
import tempfile
import uuid

from durable import atomic_write_json
from guest_boundary_receipt import validate_metadata
from interactive_machine_auth import NAME, UUID
from managed_cli_guard import require_managed_namespace
from model_network_admission import check_network
from observed_boundary_admission import make_boundary_check
from sandbox_capacity_probe import ROOT, inventory
from sandbox_runtime import SandboxRuntime
from validation_snapshot_input import _file
from validation_dispatch_receipt import _pairs


def main():
    require_managed_namespace()
    registration = json.loads(_file(ROOT/'sandbox-registry.json', 1048576), object_pairs_hook=_pairs)
    entry = registration['roles']['machine']
    if entry.get('name') != NAME or entry.get('id') != UUID:
        raise ValueError('Fixed machine identity required')
    source = _file(ROOT/'guest_boundary_metadata.py', 32768).decode('utf-8')
    marker = 'EBASE_BOUNDARY_'+uuid.uuid4().hex+':'
    work = ROOT/tempfile.mkdtemp(prefix='guest-boundary-', dir=ROOT)
    record = dict(schema=1, phase='checking', all_vms_stopped=False,
                  network_changed=False, full_boundary_accepted=False)
    atomic_write_json(work/'receipt.json', record)
    try:
        with SandboxRuntime(registration, work) as runtime:
            inventory(registration)
            check_network(runtime, 'machine', stage='initial', repo=None, timeout=45)
            boundary = make_boundary_check('sha256:df7d566115e4d16b23a0477be5677ea0eb569de027bc1933238859a6f62293fd')
            boundary(runtime, 'machine', stage='initial', repo=None, timeout=60)
            with runtime.role('machine') as repo:
                # A single namespace is required for function global resolution.
                code = "import sys,json; scope={'__name__':'probe'}; exec(compile(sys.argv[1],'<trusted-boundary>','exec'),scope); print(sys.argv[2]+json.dumps(scope['collect']()),flush=True)"
                result = repo.controller.execute(['/usr/bin/python3', '-I', '-c', code, source, marker],
                    cwd='/', log_path=work/'metadata.log', timeout=30, max_log_bytes=16384,
                    external_stop=repo.external_stop)
                if result.returncode != 0:
                    raise RuntimeError('Metadata probe failed')
                lines = [line[len(marker):] for line in _file(work/'metadata.log', 16384).decode('utf-8').splitlines()
                         if line.startswith(marker)]
                if len(lines) != 1:
                    raise ValueError('Missing or ambiguous metadata')
                metadata = validate_metadata(json.loads(lines[0], object_pairs_hook=_pairs))
                record['metadata'] = metadata
                from inspect_host_integrations import registration_metadata
                response = runtime.transport.control(['/usr/bin/sbx','inspect',NAME,'--json'],10)
                if response.returncode or len(response.stdout.encode())>1048576:
                    raise ValueError('Active manager schema unavailable')
                record['active_manager_metadata'] = registration_metadata(
                    json.loads(response.stdout,object_pairs_hook=_pairs))
                boundary(runtime, 'machine', stage='before_prepare', repo=repo, timeout=90)
                record['observed_boundary_contract_verified'] = True
            check_network(runtime, 'machine', stage='initial', repo=None, timeout=45)
            inventory(registration)
            record.update(phase='complete', all_vms_stopped=True)
    finally:
        atomic_write_json(work/'receipt.json', record)
        print(json.dumps({'evidence':str(work),'phase':record['phase'],
                         'active_manager_metadata':record.get('active_manager_metadata')}),flush=True)
    print(json.dumps(dict(evidence=str(work), **record)), flush=True)


if __name__ == '__main__':
    import sys
    if sys.argv[1:]:
        raise ValueError('Fixed no-argument inspection required')
    main()
