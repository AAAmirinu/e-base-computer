"""Dedicated-Linux maintenance CLI. Deliberately no start/resume/model command."""
import argparse
import json
import os
from pathlib import Path
import stat
import sys

from sandbox_control import LinuxTransport
from sandbox_runtime import SandboxRuntime
from sandbox_sync_recovery import inspect_sync_recovery, _receipt
from sandbox_turn_fence import inspect_turn_fences
from candidate_review_store import inspect_candidate, inspect_candidates


def _dedicated_environment():
    if sys.platform != 'linux' or os.environ.get('WSL_DISTRO_NAME') != 'EBase-Sandboxes':
        raise ValueError('Run only in the dedicated EBase-Sandboxes Linux environment')
    import pwd
    if pwd.getpwuid(os.getuid()).pw_name != 'fleet':
        raise ValueError('Dedicated fleet user required')


def _absolute(value):
    path = Path(value)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('Explicit absolute path required')
    return path


def _read(path, maximum=65536):
    path = _absolute(path)
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) |
                         getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(descriptor, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('Regular input file required')
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError('Input exceeds maintenance bound')
    return raw


def _json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate input key')
            result[key] = value
        return result
    def invalid(value):
        raise ValueError('Unsupported numeric input')
    value = json.loads(raw.decode('utf-8'), object_pairs_hook=unique,
                       parse_float=invalid, parse_constant=invalid)
    if not isinstance(value, dict):
        raise ValueError('JSON object required')
    return value


def _private_root(value):
    path = _absolute(value)
    if any(stat.S_ISLNK(parent.lstat().st_mode) for parent in path.parents):
        raise ValueError('Symlink controller ancestor refused')
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError('Existing private controller directory required')
    if os.name != 'nt' and (info.st_uid != os.getuid() or info.st_mode & 0o077):
        raise ValueError('Controller directory must be owned by fleet and private')
    return path


def execute(args, transport=None):
    root = _private_root(args.root)
    registration = _json(_read(args.registry))
    if args.command == 'inspect-turns':
        return inspect_turn_fences(root, registration)
    if args.command == 'inspect-candidates':
        return inspect_candidates(root, registration)
    if args.command == 'inspect-candidate':
        return inspect_candidate(root, registration, args.operation)
    transport = transport if transport is not None else LinuxTransport()
    # Validate exact role/UUID/capacity registration, without entering/starting VMs.
    runtime = SandboxRuntime(registration, root, capacity=1, transport=transport)
    if args.command == 'status':
        result = transport.control(['/usr/bin/sbx', 'ls', '--json'], 30)
        if result.returncode or len(result.stdout.encode('utf-8')) > 1024 * 1024:
            raise ValueError('Sandbox inventory unavailable or oversized')
        rows = _json(result.stdout.encode('utf-8')).get('sandboxes')
        if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
            raise ValueError('Malformed sandbox inventory')
        states = {}
        for role, expected in registration['roles'].items():
            matches = [r for r in rows if r.get('name') == expected['name']]
            valid = (len(matches) == 1 and matches[0].get('id') == expected['id'] and
                     matches[0].get('status') in ('running', 'stopped'))
            states[role] = matches[0]['status'] if valid else 'identity_or_state_mismatch'
        return {'roles': states, 'stop_requested': os.path.lexists(root / 'STOP'),
                'mode': 'maintenance_only', 'resume_available': False}
    if args.command != 'inspect-sync':
        raise ValueError('Unsupported maintenance command')
    if os.path.lexists(root / 'STOP'):
        raise ValueError('STOP is present; no recovery lease will be started')
    raw = _read(args.receipt)
    _receipt(raw, registration, args.operation)  # Fail before lock/admission.
    evidence = _absolute(args.evidence)
    if evidence.parent != root or os.path.lexists(evidence):
        raise ValueError('Fresh direct-child evidence directory required')
    with runtime:
        return inspect_sync_recovery(runtime, raw, args.operation, evidence)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--registry', required=True)
    parser.add_argument('--root', required=True)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('status')
    commands.add_parser('inspect-turns', help='Read local replay fences only; no VM operations')
    commands.add_parser('inspect-candidates', help='Read bounded local candidate inventory; no VM operations')
    candidate = commands.add_parser('inspect-candidate', help='Verify one archived candidate; no VM operations')
    candidate.add_argument('--operation', required=True)
    inspect = commands.add_parser('inspect-sync')
    inspect.add_argument('--receipt', required=True)
    inspect.add_argument('--operation', required=True)
    inspect.add_argument('--evidence', required=True)
    args = parser.parse_args(argv)
    try:
        _dedicated_environment()
        result = execute(args)
    except (ValueError, RuntimeError, OSError) as exc:
        print('Maintenance refused: ' + str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
