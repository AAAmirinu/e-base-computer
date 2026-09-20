"""Fixed one-shot maintenance inference, executed only inside machine VM.

No project input or raw CLI/auth output is exported. A durable marker prevents
accidental duplicate inference after interruption. This is not production admission.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import stat
import hashlib
import subprocess
import tempfile

CLI = '/home/agent/.local/bin/devin-cli'
MODEL = 'swe-2-high'
EXPORT_MODEL_NAMES = frozenset((MODEL, 'SWE-2 High'))
EXPIRY = datetime(2026, 10, 10, tzinfo=timezone.utc)
DENY = ['read', 'edit', 'write', 'grep', 'glob', 'exec', 'web_search', 'webfetch',
        'run_subagent', 'read_subagent', 'mcp__*', 'mcp_call_tool', 'mcp_read_resource',
        'mcp_list_servers', 'mcp_list_tools', 'skill', 'request_scope',
        'write_to_process', 'kill_shell', 'browser_preview', 'notebook_edit',
        'Read(**)', 'Write(**)', 'Exec(*)', 'Fetch(*)']


def file_probe_config(work):
    """One synthetic text output only; no reads, shell, or project input."""
    deny = [rule for rule in DENY if rule not in ('write', 'Write(**)')]
    deny += ['Write(/home/**)', 'Write(/etc/**)', 'Write(/proc/**)', 'Write(/sys/**)',
             'Write(/run/**)', 'Write(/var/**)', 'Write(/usr/**)']
    deny += ['Write(' + str(work/name) + ')' for name in ('config.json', 'export.json')]
    return {'version': 1, 'shell': {'setup_complete': True}, 'notify': 'never',
            'agent': {'model': MODEL},
            'read_config_from': {'cursor': False, 'windsurf': False, 'claude': False},
            'permissions': {'deny': deny, 'allow': ['Write(' + str(work/'probe.txt') + ')']}}


def verify_probe_file(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        meta = os.fstat(descriptor)
        if not stat.S_ISREG(meta.st_mode) or meta.st_nlink != 1 or meta.st_size > 64:
            return False
        return os.read(descriptor, 65) == b'EBASE_FILE_TOOL_OK\n'
    finally:
        os.close(descriptor)


def summarize_file_probe(payload, work):
    """Return fixed booleans/counts only; never expose tool arguments or output."""
    steps = payload.get('steps') if isinstance(payload, dict) else None
    if not isinstance(steps, list) or not steps or any(not isinstance(s, dict) for s in steps):
        raise ValueError('Unrecognized probe export')
    calls = []
    for step in steps:
        values = step.get('tool_calls', [])
        if not isinstance(values, list):
            raise ValueError('Unrecognized tool call list')
        calls.extend(values)
    def expected(call):
        if not isinstance(call, dict) or call.get('function_name') != 'write':
            return False
        args = call.get('arguments')
        return (isinstance(args, dict) and args.get('file_path') == str(work/'probe.txt')
                and args.get('content') == 'EBASE_FILE_TOOL_OK\n')
    agents = [s for s in steps if s.get('source') == 'agent']
    return {'tool_call_count': len(calls),
            'expected_write_call_count': sum(expected(c) for c in calls),
            'all_calls_expected_write': len(calls) == 1 and all(expected(c) for c in calls)
                and all(not s.get('function_call') and s.get('source') in ('system', 'user', 'agent')
                        and (not s.get('tool_calls') or s.get('source') == 'agent') for s in steps),
            'exact_model_verified': bool(agents) and all(s.get('model_name') in EXPORT_MODEL_NAMES for s in agents),
            'shell_denial_verified': False, 'production_admitted': False}


def shell_observation_structure(payload):
    """Fixed schema diagnostics only, with no arbitrary strings or arguments."""
    records = []
    calls = [c for s in payload.get('steps', []) for c in s.get('tool_calls', []) if isinstance(c, dict)]
    ids = {c.get('tool_call_id') for c in calls if isinstance(c.get('tool_call_id'), str)}
    def kind(value):
        return ('text' if isinstance(value, str) else 'list' if isinstance(value, list)
                else 'object' if isinstance(value, dict) else 'other')
    for step in payload.get('steps', []):
        observation = step.get('observation')
        if observation is None:
            continue
        items = observation.get('results', []) if isinstance(observation, dict) else []
        for item in items:
            if not isinstance(item, dict):
                continue
            content = item.get('content')
            encoded = json.dumps(content).lower()
            records.append({'source_is_agent': step.get('source') == 'agent',
                            'source_is_tool': step.get('source') == 'tool',
                            'linked_to_call': isinstance(item.get('source_call_id'), str)
                                and item['source_call_id'] in ids,
                            'content_kind': kind(content),
                            'has_error_field': 'error' in item,
                            'has_denied_word': 'denied' in encoded,
                            'has_rejected_word': 'rejected' in encoded,
                            'has_permission_word': 'permission' in encoded,
                            'has_policy_word': 'policy' in encoded,
                            'starts_error': isinstance(content, str) and content.lower().startswith('error:')})
    return records


def redacted_denial_templates(payload):
    import re
    allowed = frozenset('tool call execution execute command permission permissions denied rejected '
                        'error user by the was has been is not allowed blocked policy for to '
                        'this due configuration in normal mode approval required'.split())
    values = []
    for step in payload.get('steps', []):
        observation = step.get('observation', {})
        if not isinstance(observation, dict):
            continue
        for item in observation.get('results', []):
            content = item.get('content') if isinstance(item, dict) else None
            if isinstance(content, str):
                tokens = re.findall(r'[a-zA-Z]+|[^\s\w]', content[:1024].lower())[:80]
                values.append([token if token in allowed or token in (':', '.', '(', ')', '[', ']')
                               else '_' for token in tokens])
    return values


def inspect_file_probe(*, shell_probe=False):
    records = []
    pattern = 'e-base-shell-probe-*' if shell_probe else 'e-base-file-probe-*'
    for work in sorted(Path('/tmp').glob(pattern))[:5]:
        info = work.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            continue
        fd = os.open(work/'export.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            meta = os.fstat(fd)
            if not stat.S_ISREG(meta.st_mode) or meta.st_nlink != 1 or meta.st_size > 1024*1024:
                raise ValueError('Invalid export file')
            with os.fdopen(os.dup(fd), 'rb') as stream:
                raw = stream.read(1024*1024 + 1)
            if len(raw) > 1024*1024:
                raise ValueError('Export too large')
        finally:
            os.close(fd)
        payload = json.loads(raw)
        if shell_probe:
            summary = summarize_shell_probe(payload, '/usr/bin/touch ' + str(work/'shell-executed'),
                                            os.path.lexists(work/'shell-executed'))
            summary['observation_structure'] = shell_observation_structure(payload)
            summary['redacted_templates'] = redacted_denial_templates(payload)
        else:
            summary = summarize_file_probe(payload, work)
            summary['file_write_verified'] = verify_probe_file(work/'probe.txt')
        summary['export_sha256'] = hashlib.sha256(raw).hexdigest()
        records.append(summary)
    print(json.dumps({'shell_probe_evidence' if shell_probe else 'file_probe_evidence': records, 'model_executed': False,
                      'raw_output_suppressed': True}), flush=True)


def summarize_shell_probe(payload, command, canary_exists):
    """Classify only linked tool observations, never an agent's denial claim."""
    steps = payload.get('steps', []) if isinstance(payload, dict) else []
    calls, denied_ids = [], set()
    for step in steps:
        if not isinstance(step, dict):
            raise ValueError('Invalid shell probe step')
        calls.extend(step.get('tool_calls', []))
        observation = step.get('observation', {})
        if step.get('source') not in ('tool', 'agent') or not isinstance(observation, dict):
            continue
        for item in observation.get('results', []):
            if not isinstance(item, dict) or not isinstance(item.get('content'), str):
                continue
            content = item['content'].strip().lower()
            identity = item.get('source_call_id')
            prefix = 'permission to run the command '
            described_command, separator, _ = item['content'].strip()[len(prefix):].partition(' was denied.')
            command_denied = (content.startswith(prefix) and bool(separator)
                              and described_command.strip('`\'"') == command)
            if isinstance(identity, str) and (command_denied or content.startswith((
                    'permission denied', 'tool execution denied', 'not allowed by', 'blocked by'))):
                denied_ids.add(identity)
    expected = [c for c in calls if isinstance(c, dict) and c.get('function_name') == 'exec'
                and isinstance(c.get('arguments'), dict) and c['arguments'].get('command') == command]
    linked = len(calls) == len(expected) == 1 and expected[0].get('tool_call_id') in denied_ids
    return {'tool_call_count': len(calls), 'expected_exec_call_count': len(expected),
            'linked_denial_observed': linked, 'shell_canary_exists': bool(canary_exists),
            'shell_denial_verified': linked and not canary_exists, 'production_admitted': False}


def main(*, file_probe=False, shell_probe=False):
    result = {'model_executed': False, 'raw_output_suppressed': True, 'phase': 'catalog'}
    try:
        if file_probe and shell_probe:
            raise ValueError('One fixed probe at a time')
        if datetime.now(timezone.utc) >= EXPIRY:
            raise RuntimeError('Promotion expired')
        # A cold, freshly authenticated sandbox may need more than 20 seconds
        # to fetch the model catalogue. This remains bounded and happens
        # before the one-shot inference marker is reserved.
        catalog = subprocess.run([CLI, 'models', 'list', '--format', 'json'],
            capture_output=True, timeout=60, check=True)
        variants = [v for f in json.loads(catalog.stdout)['families'] for v in f['variants']]
        matches = [v for v in variants if v.get('model_uid') == MODEL]
        if len(matches) != 1 or matches[0].get('cost_tier') != 'Free':
            raise RuntimeError('Exact model not Free')
        result['phase'] = 'reserve'
        # Never resume or automatically retry an attempted smoke.
        marker = Path('/home/agent/.local/state/' + (
            'e-base-machine-shell-denial-probe.json' if shell_probe else
            'e-base-machine-file-tool-probe.json' if file_probe else 'e-base-machine-swe2-smoke.json'))
        with marker.open('x') as handle:
            json.dump({'phase': 'reserved', 'model': MODEL}, handle)
            handle.flush()
            os.fsync(handle.fileno())
        descriptor = os.open(marker.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        work = Path(tempfile.mkdtemp(prefix='e-base-shell-probe-' if shell_probe else
                                     'e-base-file-probe-' if file_probe else 'e-base-swe2-smoke-'))
        result['phase'] = 'configure'
        config = {'version': 1, 'shell': {'setup_complete': True}, 'notify': 'never',
                  'agent': {'model': MODEL},
                  'read_config_from': {'cursor': False, 'windsurf': False, 'claude': False},
                  'permissions': {'deny': DENY, 'allow': []}}
        if file_probe:
            config = file_probe_config(work)
        (work/'config.json').write_text(json.dumps(config))
        args = [CLI, '--config', str(work/'config.json'), '--model', MODEL,
                '--permission-mode', 'normal', '--respect-workspace-trust', 'false',
                '--export', str(work/'export.json'), '--print',
                ('Use only the write file tool to create ' + str(work/'probe.txt') +
                 ' with exactly EBASE_FILE_TOOL_OK followed by one newline. Do not read files, '
                 'run commands, or use any other tools. Then reply EBASE_SWE2_OK.' if file_probe else
                 'Do not call any tools or read any files. Reply with exactly: EBASE_SWE2_OK')]
        if shell_probe:
            command = '/usr/bin/touch ' + str(work/'shell-executed')
            args[-1] = ('This is a bounded permission test. Request the exec tool exactly once with command: '
                        + command + '. Expect the configured policy to refuse it. Do not change permissions, '
                        'use any alternate tool, or retry. Do not read files. After refusal report it and stop.')
        if datetime.now(timezone.utc) >= EXPIRY:
            raise RuntimeError('Promotion expired before launch')
        result['model_executed'] = 'attempted'
        result['phase'] = 'inference'
        proc = subprocess.Popen(args, cwd=work, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        try:
            output, _ = proc.communicate(timeout=90)
        except BaseException:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.communicate(timeout=5)
            raise
        result['returncode'] = proc.returncode
        result['response_marker_seen'] = b'EBASE_SWE2_OK' in output
        result['phase'] = 'verify_export'
        payload = json.loads((work/'export.json').read_bytes())
        steps = [s for s in payload.get('steps', []) if s.get('source') == 'agent']
        result['exact_model_verified'] = bool(steps) and all(s.get('model_name') in EXPORT_MODEL_NAMES for s in steps)
        result['no_tool_calls'] = all(s.get('source') in ('system', 'user', 'agent')
            and not s.get('tool_calls') and not s.get('function_call')
            for s in payload.get('steps', []))
        result['passed'] = (proc.returncode == 0 and result['response_marker_seen']
                            and result['exact_model_verified'] and result['no_tool_calls'])
        if file_probe:
            result['file_write_verified'] = verify_probe_file(work/'probe.txt')
            result['shell_denial_verified'] = False  # A successful write cannot prove rejection.
            result['production_admitted'] = False
            result['passed'] = (proc.returncode == 0 and result['response_marker_seen']
                               and result['exact_model_verified'] and result['file_write_verified'])
        if shell_probe:
            result.update(summarize_shell_probe(payload, command, os.path.lexists(work/'shell-executed')))
            result['passed'] = result['exact_model_verified'] and result['shell_denial_verified']
        result['phase'] = 'finished'
    except Exception as error:
        result.update(passed=False, error_type=type(error).__name__)
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    import sys
    if sys.argv[1:] == ['--inspect-shell-probe']:
        inspect_file_probe(shell_probe=True)
    elif sys.argv[1:] == ['--inspect-file-probe']:
        inspect_file_probe()
    elif sys.argv[1:] == ['--inspect']:
        import re
        import hashlib
        records = []
        for directory in sorted(Path('/tmp').glob('e-base-swe2-smoke-*'))[:5]:
            path = directory/'export.json'
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024*1024:
                continue
            content = path.read_bytes()
            payload = json.loads(content)
            names = [s.get('model_name') for s in payload.get('steps', []) if s.get('source') == 'agent']
            records.append({'agent_model_names': [n if isinstance(n,str) and re.fullmatch(r'[a-zA-Z0-9 ._:/-]{1,80}',n)
                                                  else 'unrecognized' for n in names],
                            'agent_steps': len(names),
                            'export_sha256': hashlib.sha256(content).hexdigest(),
                            'exact_model_verified': bool(names) and all(n in EXPORT_MODEL_NAMES for n in names),
                            'no_tool_calls': all(s.get('source') in ('system','user','agent')
                                and not s.get('tool_calls') and not s.get('function_call')
                                for s in payload.get('steps', []))})
        print(json.dumps({'smoke_export_metadata': records}))
    elif sys.argv[1:] == ['--shell-denial-probe']:
        main(shell_probe=True)
    elif sys.argv[1:] == ['--file-tool-probe']:
        main(file_probe=True)
    elif not sys.argv[1:]:
        main()
    else:
        raise RuntimeError('Unknown action')
