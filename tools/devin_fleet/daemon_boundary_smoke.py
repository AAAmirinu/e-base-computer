"""Explicit maintenance experiment; always restore the original daemon mode.

No models, clipboard accesses, policy edits, or credential copies.
Optional --validation-lifecycle starts only the registered validation VM.
Run as root only in the dedicated distro, while all registered VMs are stopped.
This is NOT the production service installer or an autostart-boundary claim.
"""
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import argparse

from durable import atomic_write_json

UNIT = 'e-base-sandboxd-boundary-test.service'
ROOT = Path('/home/fleet/controller-validation')
CLI = ['runuser', '-u', 'fleet', '--', 'sh', '/home/fleet/sbx-headless.sh']
PIDFILE = Path('/home/fleet/.local/state/sandboxes/sandboxes/sandboxd/sandboxd.pid')


def command(args, timeout=30, allowed_codes=(0,)):
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, start_new_session=True)
    try:
        output, _ = proc.communicate(timeout=timeout)
    except BaseException:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.communicate(timeout=5)
        raise
    if proc.returncode not in allowed_codes:
        raise RuntimeError('Maintenance command failed: ' + args[0] + ' exit=' + str(proc.returncode))
    return output


def inventory(prefix=None):
    rows = json.loads(command((prefix or CLI) + ['ls', '--json']))['sandboxes']
    if len(rows) != 11 or any(row['status'] != 'stopped' for row in rows):
        raise RuntimeError('Exactly eleven stopped sandboxes required')
    return {row['name']: row['id'] for row in rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--validation-lifecycle', action='store_true')
    parser.add_argument('--managed-status', action='store_true')
    parser.add_argument('--controller-status', action='store_true')
    args = parser.parse_args()
    if os.getuid() != 0 or os.environ.get('WSL_DISTRO_NAME') != 'EBase-Sandboxes':
        raise RuntimeError('Dedicated distro root required')
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda number, frame: (_ for _ in ()).throw(RuntimeError('Interrupted')))
    # Existing fleet-owned lock: root must not recreate/open it with O_CREAT in
    # sticky /tmp (protected_regular). flock also works on a read-only handle.
    with open('/tmp/e-base-devin-fleet-global.lock', 'r') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        before = inventory()
        old_pid = int(PIDFILE.read_text().strip())
        if Path(f'/proc/{old_pid}/cmdline').read_bytes().split(b'\0')[:3] != [b'/usr/bin/sbx', b'daemon', b'start']:
            raise RuntimeError('Original daemon PID identity mismatch')
        registry = json.loads((ROOT / 'sandbox-registry.json').read_text())
        expected = {value['name']: value['id'] for value in registry['roles'].values()}
        expected['e-base-validation'] = '84a0fc99-4cbb-4383-a1df-4c22bbe0d2e6'
        if before != expected:
            raise RuntimeError('Registered identity mismatch')
        state = command(['systemctl', 'show', UNIT, '--property=LoadState', '--value']).strip()
        if state != 'not-found':
            raise RuntimeError('Existing experiment service requires inspection')
        work = Path(tempfile.mkdtemp(prefix='daemon-boundary-', dir=ROOT))
        record = {'schema': 1, 'phase': 'prepared', 'identities': before,
                  'models_executed': False, 'full_boundary_accepted': False}
        def save():
            atomic_write_json(work/'receipt.json', record)
        save()
        print('evidence=' + str(work), flush=True)
        stopped_original = False
        validation_attempted = False
        try:
            # Mark uncertainty before the stop call, so its partial failure also
            # enters restoration rather than forgetting daemon ownership.
            stopped_original = True
            command(CLI + ['daemon', 'stop'])
            record['phase'] = 'original_stopped'
            save()
            command(['systemd-run', '--unit='+UNIT, '--collect', '--property=User=fleet',
                '--property=PrivatePIDs=yes', '--property=Restart=no',
                '--property=KillMode=control-group', '--property=TimeoutStopSec=30',
                '--property=WorkingDirectory=/home/fleet',
                '--property=Environment=HOME=/home/fleet',
                '--property=Environment=WSL_DISTRO_NAME=EBase-Sandboxes',
                '--property=UnsetEnvironment=DISPLAY WAYLAND_DISPLAY PULSE_SERVER DBUS_SESSION_BUS_ADDRESS SSH_AUTH_SOCK SSH_AGENT_PID XDG_RUNTIME_DIR',
                '--property=InaccessiblePaths=/mnt/wslg',
                '--property=InaccessiblePaths=/tmp/.X11-unix',
                '--property=InaccessiblePaths=/run/WSL',
                '--property=InaccessiblePaths=/run/user/1000/bus',
                '/usr/bin/sbx', 'daemon', 'start'])
            time.sleep(3)
            pid = int(command(['systemctl', 'show', UNIT, '--property=MainPID', '--value']).strip())
            if pid <= 1 or command(['systemctl', 'is-active', UNIT]).strip() != 'active':
                raise RuntimeError('Constrained daemon not active')
            record.update(phase='service_active', main_pid=pid,
                pid_namespace=os.readlink(f'/proc/{pid}/ns/pid'),
                mount_namespace=os.readlink(f'/proc/{pid}/ns/mnt'))
            save()
            namespace_pids = [line for line in Path(f'/proc/{pid}/status').read_text().splitlines()
                              if line.startswith('NSpid:')]
            if len(namespace_pids) != 1 or int(PIDFILE.read_text().strip()) != int(namespace_pids[0].split()[-1]):
                raise RuntimeError('Daemon PID file does not match namespace identity')
            confined_cli = ['nsenter', '--target', str(pid), '--mount', '--pid', '--'] + CLI
            probe = json.loads(command(['nsenter', '--target', str(pid), '--mount', '--pid', '--',
                'runuser', '-u', 'fleet', '--', '/usr/bin/python3', '-I',
                str(ROOT/'display_boundary_probe.py')]))
            hidden = ('/mnt/wslg/runtime-dir/wayland-0', '/tmp/.X11-unix/X0', '/run/WSL/1_interop')
            if (any(probe['paths'][path].get('errno') != 13 for path in hidden) or
                    probe['paths']['/run/user/1000/bus'].get('write_access') is not False or
                    probe['abstract_display_socket_names']):
                raise RuntimeError('Actual daemon namespace display probe failed')
            record['display_probe'] = probe
            save()
            # Never query the isolated daemon from an ordinary outer CLI: its
            # PID-file assumptions could cause an unconfined implicit autostart.
            if inventory(confined_cli) != before:
                raise RuntimeError('Inventory changed')
            if int(command(['systemctl', 'show', UNIT, '--property=MainPID', '--value'])) != pid:
                raise RuntimeError('Daemon identity changed during query')
            record['phase'] = 'inventory_verified'
            save()
            print('constrained_daemon_inventory_verified', flush=True)
            if args.managed_status:
                from managed_sandbox_status import run_status
                rows = run_status(unit=UNIT)['sandboxes']
                if ({row['name']: row['id'] for row in rows} != before or
                        any(row['status'] != 'stopped' for row in rows)):
                    raise RuntimeError('Pinned namespace status mismatch')
                record['managed_status_verified'] = True
                save()
            if args.controller_status:
                from managed_sandbox_status import run_status
                status = run_status(unit=UNIT, controller=True)
                if (status.get('mode') != 'maintenance_only' or status.get('resume_available') is not False or
                        set(status.get('roles', {})) != set(registry['roles']) or
                        any(v != 'stopped' for v in status['roles'].values())):
                    raise RuntimeError('Managed controller status mismatch')
                record['controller_status'] = status
                save()
            if args.validation_lifecycle:
                def check_deny():
                    policy = json.loads(command(confined_cli + ['policy', 'check', 'network',
                        '--sandbox', 'e-base-validation', '--json', 'registry-1.docker.io'], allowed_codes=(0, 1)))
                    if policy.get('allowed') is not False:
                        raise RuntimeError('Validation registry deny policy missing')
                check_deny()
                record['phase'] = 'validation_starting'
                save()
                try:
                    validation_attempted = True
                    command(confined_cli + ['exec', 'e-base-validation', '/usr/bin/true'], timeout=60)
                    record['trusted_guest_command_succeeded'] = True
                finally:
                    command(confined_cli + ['stop', 'e-base-validation'], timeout=30)
                    if inventory(confined_cli) != before:
                        raise RuntimeError('Post-validation stopped identity mismatch')
                    record['validation_vm_stopped'] = True
                    save()
                check_deny()
                if int(command(['systemctl', 'show', UNIT, '--property=MainPID', '--value'])) != pid:
                    raise RuntimeError('Daemon changed during VM lifecycle')
                record.update(phase='validation_lifecycle_verified', registry_policy_denied=True)
                save()
                print('constrained_validation_lifecycle_verified', flush=True)
        except BaseException as error:
            record.update(phase='experiment_failed', error_type=type(error).__name__)
            save()
            raise
        finally:
            if stopped_original:
                # Never start a second daemon if the temporary service failed to stop.
                if command(['systemctl', 'show', UNIT, '--property=LoadState', '--value']).strip() != 'not-found':
                    command(['systemctl', 'stop', UNIT], timeout=40)
                if command(['systemctl', 'show', UNIT, '--property=MainPID', '--value']).strip() not in ('0', ''):
                    raise RuntimeError('Temporary daemon did not stop')
                if validation_attempted and record.get('validation_vm_stopped') is not True:
                    record['restoration_held'] = 'validation_cleanup_unverified'
                    save()
                    raise RuntimeError('VM cleanup unverified; ordinary daemon restoration withheld')
                command(CLI + ['daemon', 'start', '--detach'])
                if inventory() != before:
                    raise RuntimeError('Restored inventory mismatch')
                record['original_mode_restored'] = True
                record['all_vms_stopped'] = True
                save()
                print(json.dumps(record), flush=True)


if __name__ == '__main__':
    main()
