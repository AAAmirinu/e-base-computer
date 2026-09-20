"""Fixed root launcher for a user-visible, unrecorded machine login terminal."""
import fcntl
import hashlib
import os
from pathlib import Path
import signal
import subprocess
import time
import types
import sys

UNIT = 'e-base-sandboxd.service'
ENTRY = Path('/usr/local/libexec/e-base-managed-status.py')
MAINTENANCE_ACTIONS = ('--inspect-policy', '--check-policy', '--catalog-check',
                       '--model-smoke', '--smoke-evidence', '--recover-machine-deny', '--capacity-probe', '--capacity-ten', '--auth-inventory')
MAINTENANCE_ACTIONS += ('--validate-earray-repair',)
MAINTENANCE_ACTIONS += ('--validate-stdlib-main',)
MAINTENANCE_ACTIONS += ('--file-tool-probe',)
MAINTENANCE_ACTIONS += ('--file-probe-evidence',)
MAINTENANCE_ACTIONS += ('--shell-denial-probe',)
MAINTENANCE_ACTIONS += ('--shell-probe-evidence',)
MAINTENANCE_ACTIONS += ('--validate-eword-baseline',)
MAINTENANCE_ACTIONS += ('--eword-edit',)
MAINTENANCE_ACTIONS += ('--validate-eword-edit',)
MAINTENANCE_ACTIONS += ('--eword-evidence',)
MAINTENANCE_ACTIONS += ('--validation-git-capability',)
MAINTENANCE_ACTIONS += ('--validation-image-info',)
MAINTENANCE_ACTIONS += ('--build-validation-git-image',)
MAINTENANCE_ACTIONS += ('--inspect-validation-git-build',)
MAINTENANCE_ACTIONS += ('--validation-newgit-capability',)
MAINTENANCE_ACTIONS += ('--validate-newgit-stdlib',)
MAINTENANCE_ACTIONS += ('--validation-newgit-active',)
MAINTENANCE_ACTIONS += ('--build-stdlib-candidate',)
MAINTENANCE_ACTIONS += ('--verify-stdlib-candidate-import',)
MAINTENANCE_ACTIONS += ('--verify-common-candidate-import',)
MAINTENANCE_ACTIONS += ('--verify-common-candidate-roundtrip',)
MAINTENANCE_ACTIONS += ('--verify-git-read-policy',)
MAINTENANCE_ACTIONS += ('--verify-git-read-timeout',)
MAINTENANCE_ACTIONS += ('--inspect-auth-interface',)
MAINTENANCE_ACTIONS += ('--inspect-auth-status-shape',)
MAINTENANCE_ACTIONS += ('--verify-model-network-closed',)
MAINTENANCE_ACTIONS += ('--inspect-guest-boundary',)
MAINTENANCE_ACTIONS += ('--inspect-host-integrations',)
MAINTENANCE_ACTIONS += ('--inspect-mcp-config-locations',)
MAINTENANCE_ACTIONS += ('--inspect-mcp-config-shape',)
MAINTENANCE_ACTIONS += ('--inspect-mcp-override',)
MAINTENANCE_ACTIONS += ('--prepare-mcp-probe',)
MAINTENANCE_ACTIONS += ('--inspect-mcp-prepared',)
MAINTENANCE_ACTIONS += ('--inspect-mcp-history',)
MAINTENANCE_ACTIONS += ('--mcp-dispatch-preflight',)
MAINTENANCE_ACTIONS += ('--inspect-cli-link',)
MAINTENANCE_ACTIONS += ('--mcp-denial-once',)
MAINTENANCE_ACTIONS += ('--harden-machine-telemetry',)
MAINTENANCE_ACTIONS += ('--inspect-catalog-logs',)
MAINTENANCE_ACTIONS += ('--inspect-mcp-result',)
MAINTENANCE_ACTIONS += ('--prepare-mcp-discovery',)
MAINTENANCE_ACTIONS += ('--inspect-mcp-discovery',)
MAINTENANCE_ACTIONS += ('--mcp-discovery-once',)
MAINTENANCE_ACTIONS += ('--inspect-discovery-result',)
MAINTENANCE_ACTIONS += ('--prepare-mcp-wildcard','--inspect-mcp-wildcard','--mcp-wildcard-once')
MAINTENANCE_ACTIONS += ('--inspect-wildcard-result',)
MAINTENANCE_ACTIONS += ('--inspect-cli-policy',)
MAINTENANCE_ACTIONS += ('--prepare-mcp-control','--inspect-mcp-control','--mcp-control-once')
MAINTENANCE_ACTIONS += ('--prepare-mcp-compatible','--inspect-mcp-compatible','--mcp-compatible-once')
MAINTENANCE_ACTIONS += ('--prepare-mcp-params','--inspect-mcp-params','--mcp-params-once')
MAINTENANCE_ACTIONS += ('--prepare-production-registration','--inspect-production-registration')
MAINTENANCE_ACTIONS += ('--check-production-readiness',)
MAINTENANCE_ACTIONS += ('--prepare-role-authentication','--inspect-role-authentication')
MAINTENANCE_ACTIONS += ('--prepare-normal-permission','--inspect-normal-permission')
MAINTENANCE_ACTIONS += ('--prepare-candidate-trial','--inspect-candidate-trial',
                        '--inspect-candidate-trial-guest','--seed-candidate-trial',
                        '--diagnose-candidate-trial-seed',
                        '--preflight-candidate-trial',
                        '--candidate-trial-once')
MAINTENANCE_ACTIONS += ('--inspect-control-result',)
MAINTENANCE_ACTIONS += ('--inspect-compatible-result',)
MAINTENANCE_ACTIONS += ('--inspect-compatible-logs',)
MAINTENANCE_ACTIONS += ('--resolve-trial-v5-harness-failure',)
LOGIN_ROLES = ('machine', 'coordinator', 'toolchain', 'kernel', 'stdlib', 'storage',
               'services', 'applications', 'devtools', 'assurance')


def model_recovery_command(arguments):
    if not arguments or arguments[0]!='--recover-model-network':
        return None
    if len(arguments)!=2 or arguments[1] not in LOGIN_ROLES:
        raise RuntimeError('Exactly one fixed model recovery role required')
    return ['/home/fleet/controller-validation/recover_model_network.py','--role',arguments[1]]


def registered_turn_command(arguments):
    if not arguments or arguments[0]!='--registered-turn-once':
        return None
    import re
    if len(arguments)!=2 or re.fullmatch('[0-9a-f]{32}',arguments[1]) is None:
        raise RuntimeError('Exactly one registered turn identity required')
    return ['/home/fleet/controller-validation/registered_turn_entry.py','--once',arguments[1]]


def role_model_smoke_command(arguments):
    if not arguments or arguments[0]!='--model-smoke-role':
        return None
    if len(arguments)!=2 or arguments[1] not in LOGIN_ROLES:
        raise RuntimeError('Exactly one fixed model smoke role required')
    return ['/home/fleet/controller-validation/interactive_machine_auth.py',
            '--model-smoke-role',arguments[1]]


def role_auth_inventory_command(arguments):
    if not arguments or arguments[0]!='--auth-inventory-role':
        return None
    if len(arguments)!=2 or arguments[1] not in LOGIN_ROLES:
        raise RuntimeError('Exactly one fixed auth inventory role required')
    return ['/home/fleet/controller-validation/sandbox_auth_inventory.py','--role',arguments[1]]


def main():
    registered_turn=registered_turn_command(sys.argv[1:])
    role_model_smoke=role_model_smoke_command(sys.argv[1:])
    role_auth_inventory=role_auth_inventory_command(sys.argv[1:])
    model_recovery=model_recovery_command(sys.argv[1:])
    role_recovery = (len(sys.argv) == 3 and sys.argv[1] == '--recover-role'
                     and sys.argv[2] in LOGIN_ROLES)
    maintenance = ((len(sys.argv) == 2 and sys.argv[1] in MAINTENANCE_ACTIONS)
                   or role_recovery or model_recovery is not None or registered_turn is not None
                   or role_model_smoke is not None or role_auth_inventory is not None)
    role_login = (len(sys.argv) == 3 and sys.argv[1] == '--login-role'
                  and sys.argv[2] in LOGIN_ROLES)
    hold_child_lock = sys.argv[1:] in (['--prepare-production-registration'],
                                      ['--inspect-production-registration'],
                                      ['--prepare-role-authentication'],
                                      ['--prepare-normal-permission'],
                                      ['--prepare-candidate-trial'],
                                      ['--resolve-trial-v5-harness-failure'])
    if sys.argv[1:] and not (maintenance or role_login):
        raise RuntimeError('Unknown action')
    if (os.getuid() != 0 or os.environ.get('WSL_DISTRO_NAME') != 'EBase-Sandboxes' or
            (not maintenance and not all(os.isatty(fd) for fd in (0, 1, 2)))):
        raise RuntimeError('Dedicated private interactive terminal required')
    source = ENTRY.read_bytes()
    if hashlib.sha256(source).hexdigest() != 'bc85d5b41c81538fd85a1870881f375f8dd3213d9525453a0e7be953b0e0ba48':
        raise RuntimeError('Managed entry version mismatch')
    managed = types.ModuleType('installed_entry')
    exec(compile(source, str(ENTRY), 'exec'), managed.__dict__)
    if managed.service_info(UNIT)['ActiveState'] != 'inactive':
        raise RuntimeError('Existing service requires inspection before login')
    descriptors = []
    child = None
    lock = None
    def interrupted(number, frame):
        raise KeyboardInterrupt('Authentication terminal interrupted')
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, interrupted)
    try:
        subprocess.run(['/usr/bin/systemctl', 'start', UNIT], check=True, timeout=40)
        deadline = time.monotonic() + 15
        while True:
            pid = managed.validate_service(managed.service_info(UNIT))
            status = Path(f'/proc/{pid}/status').read_text()
            namespace_pid = next(line.split()[-1] for line in status.splitlines() if line.startswith('NSpid:'))
            pidfile = Path('/home/fleet/.local/state/sandboxes/sandboxes/sandboxd/sandboxd.pid')
            if pidfile.exists() and pidfile.read_text().strip() == namespace_pid:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError('Manager not ready')
            time.sleep(0.1)
        lock = open('/tmp/e-base-devin-fleet-global.lock', 'r')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        rows = managed.run_status()['sandboxes']
        if len(rows) != 11 or any(row['status'] != 'stopped' for row in rows):
            raise RuntimeError('Eleven stopped VMs required')
        for kind in ('mnt', 'pid'):
            descriptors.append(os.open(f'/proc/{pid}/ns/{kind}', os.O_RDONLY))
        if managed.validate_service(managed.service_info(UNIT)) != pid:
            raise RuntimeError('Manager changed')
        command = ['/usr/bin/nsenter', '--mount=/proc/self/fd/'+str(descriptors[0]),
            '--pid=/proc/self/fd/'+str(descriptors[1]), '--', '/usr/sbin/runuser', '-u', 'fleet', '--',
            '/usr/bin/python3', '-E', '-s', '/home/fleet/controller-validation/interactive_machine_auth.py']
        if role_auth_inventory is not None:
            command[-1:]=role_auth_inventory
        elif role_model_smoke is not None:
            command[-1:]=role_model_smoke
        elif sys.argv[1:] in (['--prepare-production-registration'],['--inspect-production-registration']):
            command[-1]='/home/fleet/controller-validation/production_registration_entry.py'
            command.append('--prepare' if sys.argv[1:]==['--prepare-production-registration'] else '--inspect')
        elif sys.argv[1:] == ['--check-production-readiness']:
            command[-1]='/home/fleet/controller-validation/production_readiness_entry.py'
            command.append('--check')
        elif sys.argv[1:] in (['--prepare-role-authentication'],['--inspect-role-authentication']):
            command[-1]='/home/fleet/controller-validation/production_role_authentication_entry.py'
            command.append('--prepare' if sys.argv[1:]==['--prepare-role-authentication'] else '--inspect')
        elif sys.argv[1:] in (['--prepare-normal-permission'],['--inspect-normal-permission']):
            command[-1]='/home/fleet/controller-validation/production_normal_permission_entry.py'
            command.append('--prepare' if sys.argv[1:]==['--prepare-normal-permission'] else '--inspect')
        elif sys.argv[1:] in (['--prepare-candidate-trial'],['--inspect-candidate-trial'],
                              ['--inspect-candidate-trial-guest'],
                              ['--diagnose-candidate-trial-seed'],
                              ['--seed-candidate-trial'],
                              ['--preflight-candidate-trial'],
                              ['--candidate-trial-once']):
            command[-1]='/home/fleet/controller-validation/prepared_candidate_trial_entry.py'
            actions={'--prepare-candidate-trial':'--prepare',
                     '--inspect-candidate-trial':'--inspect',
                     '--inspect-candidate-trial-guest':'--inspect-guest',
                     '--diagnose-candidate-trial-seed':'--diagnose-seed',
                     '--seed-candidate-trial':'--seed',
                     '--preflight-candidate-trial':'--preflight',
                     '--candidate-trial-once':'--once'}
            command.append(actions[sys.argv[1]])
        elif sys.argv[1:] == ['--resolve-trial-v5-harness-failure']:
            command[-1]='/home/fleet/controller-validation/validation_harness_failure_resolution.py'
        elif registered_turn is not None:
            command[-1:] = registered_turn
        elif model_recovery is not None:
            command[-1:] = model_recovery
        elif sys.argv[1:] == ['--inspect-host-integrations']:
            command[-1] = '/home/fleet/controller-validation/inspect_host_integrations.py'
        elif sys.argv[1:] == ['--inspect-guest-boundary']:
            command[-1] = '/home/fleet/controller-validation/inspect_guest_boundary.py'
        elif sys.argv[1:] == ['--verify-model-network-closed']:
            command[-1] = '/home/fleet/controller-validation/model_network_admission.py'
            command.append('--verify-machine-closed')
        elif sys.argv[1:] == ['--harden-machine-telemetry']:
            command[-1] = '/home/fleet/controller-validation/harden_machine_telemetry.py'
            command.append('--closed-only')
        elif sys.argv[1:] == ['--catalog-check']:
            command[-1] = '/home/fleet/controller-validation/catalog_diagnostic.py'
            command.append('--once')
        elif sys.argv[1:] == ['--inspect-compatible-result']:
            command[-1] = '/home/fleet/controller-validation/inspect_mcp_result.py'
            command.append('--compatible')
        elif sys.argv[1:] == ['--inspect-control-result']:
            command[-1] = '/home/fleet/controller-validation/inspect_mcp_result.py'
            command.append('--control')
        elif sys.argv[1:] == ['--inspect-wildcard-result']:
            command[-1] = '/home/fleet/controller-validation/inspect_mcp_result.py'
            command.append('--wildcard')
        elif sys.argv[1:] == ['--inspect-discovery-result']:
            command[-1] = '/home/fleet/controller-validation/inspect_mcp_result.py'
            command.append('--discovery')
        elif sys.argv[1:] == ['--inspect-mcp-result']:
            command[-1] = '/home/fleet/controller-validation/inspect_mcp_result.py'
        elif sys.argv[1:] == ['--inspect-compatible-logs']:
            command[-1] = '/home/fleet/controller-validation/inspect_catalog_logs.py'
            command.append('--compatible')
        elif sys.argv[1:] == ['--inspect-catalog-logs']:
            command[-1] = '/home/fleet/controller-validation/inspect_catalog_logs.py'
        elif sys.argv[1:] == ['--inspect-auth-status-shape']:
            command[-1] = '/home/fleet/controller-validation/inspect_auth_interface.py'
            command.append('--status-shape')
        elif sys.argv[1:] == ['--mcp-compatible-once']:
            command[-1] = '/home/fleet/controller-validation/mcp_compatible_control_entry.py'
            command.append('--once')
        elif sys.argv[1:] == ['--mcp-params-once']:
            command[-1] = '/home/fleet/controller-validation/mcp_params_control_entry.py'
            command.append('--once')
        elif sys.argv[1:] in (['--prepare-mcp-params'],['--inspect-mcp-params']):
            command[-1] = '/home/fleet/controller-validation/inspect_auth_interface.py'
            command.append(sys.argv[1])
        elif sys.argv[1:] in (['--prepare-mcp-compatible'],['--inspect-mcp-compatible']):
            command[-1] = '/home/fleet/controller-validation/inspect_auth_interface.py'
            command.append(sys.argv[1])
        elif sys.argv[1:] == ['--mcp-control-once']:
            command[-1] = '/home/fleet/controller-validation/mcp_echo_control_entry.py'
            command.append('--once')
        elif sys.argv[1:] in (['--prepare-mcp-control'],['--inspect-mcp-control']):
            command[-1] = '/home/fleet/controller-validation/inspect_auth_interface.py'
            command.append(sys.argv[1])
        elif sys.argv[1:] == ['--mcp-wildcard-once']:
            command[-1] = '/home/fleet/controller-validation/mcp_wildcard_entry.py'
            command.append('--once')
        elif sys.argv[1:] in (['--prepare-mcp-wildcard'],['--inspect-mcp-wildcard']):
            command[-1] = '/home/fleet/controller-validation/inspect_auth_interface.py'
            command.append(sys.argv[1])
        elif sys.argv[1:] == ['--mcp-discovery-once']:
            command[-1] = '/home/fleet/controller-validation/mcp_discovery_entry.py'
            command.append('--once')
        elif sys.argv[1:] == ['--mcp-denial-once']:
            command[-1] = '/home/fleet/controller-validation/mcp_probe_entry.py'
            command.append('--once')
        elif sys.argv[1:] == ['--inspect-cli-policy']:
            command[-1] = '/home/fleet/controller-validation/inspect_auth_interface.py'
            command.append('--cli-policy')
        elif sys.argv[1:] == ['--inspect-cli-link']:
            command[-1] = '/home/fleet/controller-validation/inspect_auth_interface.py'
            command.append('--cli-link')
        elif sys.argv[1:] == ['--mcp-dispatch-preflight']:
            command[-1] = '/home/fleet/controller-validation/inspect_auth_interface.py'
            command.append('--dispatch-preflight')
        elif sys.argv[1:] == ['--inspect-mcp-history']:
            command[-1] = '/home/fleet/controller-validation/inspect_auth_interface.py'
            command.append('--history-shape')
        elif sys.argv[1:] == ['--inspect-mcp-prepared']:
            command[-1] = '/home/fleet/controller-validation/inspect_auth_interface.py'
            command.append('--inspect-mcp')
        elif sys.argv[1:] == ['--inspect-mcp-discovery']:
            command[-1] = '/home/fleet/controller-validation/inspect_auth_interface.py'
            command.append('--inspect-mcp-discovery')
        elif sys.argv[1:] == ['--prepare-mcp-discovery']:
            command[-1] = '/home/fleet/controller-validation/inspect_auth_interface.py'
            command.append('--prepare-mcp-discovery')
        elif sys.argv[1:] == ['--prepare-mcp-probe']:
            command[-1] = '/home/fleet/controller-validation/inspect_auth_interface.py'
            command.append('--prepare-mcp')
        elif sys.argv[1:] == ['--inspect-mcp-override']:
            command[-1] = '/home/fleet/controller-validation/inspect_auth_interface.py'
            command.append('--mcp-override')
        elif sys.argv[1:] == ['--inspect-mcp-config-shape']:
            command[-1] = '/home/fleet/controller-validation/inspect_auth_interface.py'
            command.append('--config-shape')
        elif sys.argv[1:] == ['--inspect-mcp-config-locations']:
            command[-1] = '/home/fleet/controller-validation/inspect_auth_interface.py'
            command.append('--config-locations')
        elif sys.argv[1:] == ['--inspect-auth-interface']:
            command[-1] = '/home/fleet/controller-validation/inspect_auth_interface.py'
        elif sys.argv[1:] == ['--verify-git-read-timeout']:
            command[-1] = '/home/fleet/controller-validation/git_read_timeout_probe.py'
        elif sys.argv[1:] == ['--verify-git-read-policy']:
            command[-1] = '/home/fleet/controller-validation/validation_git_capability.py'
            command.append('--git-read-policy')
        elif sys.argv[1:] == ['--verify-common-candidate-roundtrip']:
            command[-1] = '/home/fleet/controller-validation/check_common_candidate_roundtrip.py'
        elif sys.argv[1:] == ['--verify-common-candidate-import']:
            command[-1] = '/home/fleet/controller-validation/check_common_candidate_import.py'
        elif sys.argv[1:] == ['--verify-stdlib-candidate-import']:
            command[-1] = '/home/fleet/controller-validation/run_stdlib_candidate.py'
            command.append('--verify-import')
        elif sys.argv[1:] == ['--build-stdlib-candidate']:
            command[-1] = '/home/fleet/controller-validation/run_stdlib_candidate.py'
        elif sys.argv[1:] == ['--validation-newgit-active']:
            command[-1] = '/home/fleet/controller-validation/validation_git_capability.py'
            command.append('--new-git-active')
        elif sys.argv[1:] == ['--validate-newgit-stdlib']:
            command[-1] = '/home/fleet/controller-validation/validation_snapshot_dispatch.py'
            command.extend(['--snapshot', '/home/fleet/controller-validation/stdlib-main-snapshot-6gprve05',
                            '--manifest-sha256', '6039785fee9ba2a0425c41b6999e0fa082abe49310f47e0124ab9d204ad070ff',
                            '--git-image-candidate'])
        elif sys.argv[1:] == ['--validation-newgit-capability']:
            command[-1] = '/home/fleet/controller-validation/validation_git_capability.py'
            command.append('--new-git-image')
        elif sys.argv[1:] == ['--inspect-validation-git-build']:
            command[-1] = '/home/fleet/controller-validation/build_validation_git_image.py'
            command.append('--inspect-failed-build')
        elif sys.argv[1:] == ['--build-validation-git-image']:
            command[-1] = '/home/fleet/controller-validation/build_validation_git_image.py'
        elif sys.argv[1:] == ['--validation-image-info']:
            command[-1] = '/home/fleet/controller-validation/validation_git_capability.py'
            command.append('--image-info')
        elif sys.argv[1:] == ['--validation-git-capability']:
            command[-1] = '/home/fleet/controller-validation/validation_git_capability.py'
        elif sys.argv[1:] == ['--validate-eword-edit']:
            command[-1] = '/home/fleet/controller-validation/validate_eword_edit.py'
        elif sys.argv[1:] == ['--validate-eword-baseline']:
            command[-1] = '/home/fleet/controller-validation/validation_snapshot_dispatch.py'
            command.extend(['--snapshot', '/home/fleet/controller-validation/eword-baseline-xxlcbs8p',
                            '--manifest-sha256', '47810d95844b90f04844cf85ad8a42a62f91e4c0157beeb9a19836dc12c4f2ea'])
        elif sys.argv[1:] == ['--validate-stdlib-main']:
            command[-1] = '/home/fleet/controller-validation/validation_snapshot_dispatch.py'
            command.extend(['--snapshot', '/home/fleet/controller-validation/stdlib-main-snapshot-6gprve05',
                            '--manifest-sha256', '6039785fee9ba2a0425c41b6999e0fa082abe49310f47e0124ab9d204ad070ff'])
        elif sys.argv[1:] == ['--validate-earray-repair']:
            command[-1] = '/home/fleet/controller-validation/validate_earray_repair.py'
        elif sys.argv[1:] == ['--auth-inventory']:
            command[-1] = '/home/fleet/controller-validation/sandbox_auth_inventory.py'
        elif sys.argv[1:] in (['--capacity-probe'], ['--capacity-ten']):
            command[-1] = '/home/fleet/controller-validation/sandbox_capacity_probe.py'
            if sys.argv[1:] == ['--capacity-ten']:
                command.append('--ten')
        elif maintenance or role_login:
            command.extend(sys.argv[1:])
        if not hold_child_lock:
            lock.close()
            lock = None
        # No output redirection. The user, not Codex, operates this terminal.
        child = subprocess.Popen(command, pass_fds=descriptors)
        try:
            child.wait()
        except KeyboardInterrupt:
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=120)  # Let the child's signal cleanup finish.
    finally:
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, signal.SIG_IGN)
        for fd in descriptors:
            os.close(fd)
        if child is not None and child.poll() is None:
            raise RuntimeError('Login helper still active; inspection required')
        acquired_for_cleanup = False
        if lock is None:
            lock = open('/tmp/e-base-devin-fleet-global.lock', 'r')
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired_for_cleanup = True
        try:
            rows = managed.run_status()['sandboxes']
            if len(rows) != 11 or any(row['status'] != 'stopped' for row in rows):
                raise RuntimeError('VM stop unverified; manager retained for inspection')
            subprocess.run(['/usr/bin/systemctl', 'stop', UNIT], check=True, timeout=40)
            final = managed.service_info(UNIT)
            if final['ActiveState'] != 'inactive' or final['MainPID'] != '0':
                raise RuntimeError('Manager stop unverified')
        finally:
            if lock is not None:
                lock.close()
                lock = None
        print('Managed service stopped. Return to the chat when finished.', flush=True)
    if child is not None and child.returncode != 0:
        raise RuntimeError('Maintenance child failed; cleanup completed, operation not accepted')


if __name__ == '__main__':
    main()
