"""One non-retrying candidate-container attempt in the dedicated validator.

Trusted controller callers only: packet modules are executable controller code,
not model data. This primitive does not authorize a model turn or accept a
candidate. The caller must bind registration, fence, snapshot and raw results.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import signal
import subprocess

from durable import atomic_write_json, _sync_directory
from managed_cli_guard import require_managed_namespace
from sandbox_turn_fence import _directory
from validation_snapshot_input import _file
from validation_dispatch_receipt import _pairs
from validation_snapshot_dispatch import SBX
from run_stdlib_candidate import GUEST, INNER, IMAGE
import interactive_machine_auth as policy

ROOT = Path('/home/fleet/controller-validation')


def _limit_logs():
    resource.setrlimit(resource.RLIMIT_FSIZE, (24*1024*1024, 24*1024*1024))


def execute(packet, work, *, admission):
    """Return stopped raw guest evidence, never candidate acceptance or retry."""
    require_managed_namespace()
    if not callable(admission):
        raise ValueError('Explicit registration/fence/STOP admission required')
    if not isinstance(packet, bytes) or not 0 < len(packet) <= 32*1024*1024:
        raise ValueError('Bounded trusted controller packet required')
    work = Path(work)
    if (work.parent != ROOT or work.resolve() != work
            or re.fullmatch('candidate-attempt-[0-9a-f]{32}', work.name) is None):
        raise ValueError('Exact dedicated attempt directory required')
    for parent in ROOT.parents:
        _directory(parent)
    _directory(ROOT, private=True)
    with open('/tmp/e-base-devin-fleet-global.lock', 'r') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        old_target = policy.NAME, policy.UUID
        policy.NAME, policy.UUID = 'e-base-validation', '84a0fc99-4cbb-4383-a1df-4c22bbe0d2e6'
        try:
            admission()
            return _locked(packet, work, admission)
        finally:
            policy.NAME, policy.UUID = old_target


def _locked(packet, work, admission):
    policy.stopped()
    if not any(policy.scoped_deny(rule) and rule.get('resources') == ['**'] for rule in policy.rules()):
        raise RuntimeError('Blanket validation denial required')
    if any(policy.allowed(host) is not False for host in ('example.com:443', 'deb.debian.org:443')):
        raise RuntimeError('Validation network denial not verified')
    # The directory is the durable exclusive reservation, including partial writes.
    work.mkdir(mode=0o700)
    _sync_directory(ROOT)
    receipt = dict(schema=1, phase='prepared', image_id=IMAGE,
                   all_vms_stopped=False, automatic_resume=False, production_accepted=False,
                   packet_sha256=hashlib.sha256(packet).hexdigest())
    def save():
        atomic_write_json(work/'receipt.json', receipt)
    save()
    previous = {}
    def interrupted(number, frame):
        raise KeyboardInterrupt('Candidate attempt interrupted')
    guest = None
    try:
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            previous[sig] = signal.signal(sig, interrupted)
        receipt['phase'] = 'running'
        save()
        source = 'IMAGE='+repr(IMAGE)+'\nINNER='+repr(INNER)+'\n'+GUEST
        with (work/'stdout.json').open('xb') as stdout, (work/'stderr.log').open('xb') as stderr:
            try:
                admission()
                result = subprocess.run(SBX+['exec', '-i', policy.NAME, '/usr/bin/python3', '-I', '-c', source],
                    input=packet, stdout=stdout, stderr=stderr, timeout=180, preexec_fn=_limit_logs)
            finally:
                for stream in (stdout, stderr):
                    stream.flush()
                    os.fsync(stream.fileno())
        if result.returncode != 0:
            raise RuntimeError('Candidate VM command failed')
        raw_output = _file(work/'stdout.json', 24*1024*1024)
        receipt['stdout_sha256'] = hashlib.sha256(raw_output).hexdigest()
        guest = json.loads(raw_output, object_pairs_hook=_pairs)
    except BaseException as error:
        receipt['error_type'] = type(error).__name__
        raise
    finally:
        try:
            for sig in previous:
                signal.signal(sig, signal.SIG_IGN)
            receipt['phase'] = 'inspection_required'
            try:
                policy.run('stop', policy.NAME)
                policy.stopped()
                receipt['all_vms_stopped'] = True
            except BaseException as error:
                receipt['cleanup_error_type'] = type(error).__name__
                raise
            finally:
                save()
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
    if (not isinstance(guest, dict) or guest.get('passed') is not True
            or guest.get('container_stopped') is not True or guest.get('image_id') != IMAGE
            or not isinstance(guest.get('boundary'), dict)
            or guest['boundary'].get('observations_verified') is not True
            or guest['boundary'].get('full_isolation_accepted') is not False):
        raise RuntimeError('Candidate guest result or stop unverified')
    receipt['phase'] = 'stopped_result'
    save()
    return dict(directory=str(work), guest=guest)
