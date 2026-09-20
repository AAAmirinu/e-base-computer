"""Bounded repository operations inside an already admitted SandboxController.

The caller owns the controller, its lifecycle, and a private trusted log directory.
Guest output is untrusted data, never host code. This is not an isolation attestation
or a production fleet integration; it does not provision, resume, or run a model.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import uuid

from sandbox_control import SandboxError
from guest_git_read_policy import SOURCE as READ_GIT_POLICY


class GuestRepositoryError(SandboxError):
    pass


# Fixed code runs ONLY through the guest controller, never a host interpreter.
_GUEST_CODE = READ_GIT_POLICY + r'''
import base64, hashlib, json, os, selectors, stat, subprocess, sys, uuid
marker, request = sys.argv[1], json.loads(sys.argv[2])
def envelope(ok, data=b'', error=''):
    print(marker + json.dumps({'ok': ok, 'data': base64.b64encode(data).decode('ascii'),
                               'error': error}, separators=(',', ':')), flush=True)
def open_directory(path):
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.split('/')[1:]:
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
        return fd
    except BaseException:
        os.close(fd)
        raise
try:
    root = open_directory(request['root'])
    try:
        if request['operation'] == 'mkdir':
            parts = request['relative'].split('/')
            for index, part in enumerate(parts):
                try:
                    os.mkdir(part, 0o700, dir_fd=root)
                    os.fsync(root)
                except FileExistsError:
                    if index == len(parts) - 1:
                        raise ValueError('destination already exists')
                nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
                os.close(root)
                root = nxt
            envelope(True, b'created')
        elif request['operation'] == 'kind':
            parts = request['relative'].split('/')
            for part in parts[:-1]:
                nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
                os.close(root)
                root = nxt
            info = os.stat(parts[-1], dir_fd=root, follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode):
                kind = 'symlink'
            elif stat.S_ISDIR(info.st_mode):
                kind = 'directory'
            elif stat.S_ISREG(info.st_mode):
                kind = 'regular' if info.st_nlink == 1 else 'hardlink'
            else:
                kind = 'other'
            envelope(True, kind.encode('ascii'))
        elif request['operation'] in ('read', 'fingerprint', 'snapshot_read'):
            file_limit = request.get('file_limit', request['limit'])
            parts = request['relative'].split('/')
            for part in parts[:-1]:
                nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
                os.close(root)
                root = nxt
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=root)
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode):
                    raise ValueError('not a regular file')
                if request['operation'] == 'snapshot_read' and (info.st_nlink != 1 or info.st_mode & 0o7000):
                    raise ValueError('linked or special-mode snapshot file')
                if info.st_size > file_limit:
                    raise ValueError('file exceeds limit')
                chunks, size = [], 0
                while True:
                    chunk = os.read(fd, min(65536, file_limit + 1 - size))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > file_limit:
                        raise ValueError('file exceeds limit')
                data = b''.join(chunks)
                if request['operation'] == 'snapshot_read':
                    result = {'mode': '100755' if info.st_mode & 0o111 else '100644',
                              'data': base64.b64encode(data).decode('ascii')}
                    envelope(True, json.dumps(result, separators=(',', ':')).encode('ascii'))
                else:
                    envelope(True, hashlib.sha256(data).hexdigest().encode('ascii')
                             if request['operation'] == 'fingerprint' else data)
            finally:
                os.close(fd)
        elif request['operation'] in ('write', 'assemble'):
            if request['operation'] == 'write':
                payload = base64.b64decode(request['payload'], validate=True)
                if len(payload) > 32768:
                    raise ValueError('write exceeds limit')
            else:
                count, size = request['count'], request['size']
                if type(count) is not int or not 2 <= count <= 512 or not 32768 < size <= 16777216:
                    raise ValueError('invalid transfer size')
                staging = open_directory(request['root'] + '/' + request['staging'])
                pieces = []
                try:
                    for index in range(count):
                        fd = os.open(str(index), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=staging)
                        with os.fdopen(fd, 'rb') as stream:
                            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                                raise ValueError('non-regular transfer part')
                            data = stream.read(32769)
                        expected = min(32768, size - index * 32768)
                        if len(data) != expected or expected <= 0:
                            raise ValueError('transfer part size mismatch')
                        pieces.append(data)
                finally:
                    os.close(staging)
                payload = b''.join(pieces)
                if len(payload) != size or hashlib.sha256(payload).hexdigest() != request['sha256']:
                    raise ValueError('transfer digest mismatch')
            parts = request['relative'].split('/')
            for part in parts[:-1]:
                nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
                os.close(root)
                root = nxt
            try:
                previous = os.stat(parts[-1], dir_fd=root, follow_symlinks=False)
            except FileNotFoundError:
                previous = None
            if previous is not None and not stat.S_ISREG(previous.st_mode):
                raise ValueError('destination is not regular')
            temporary = '.fleet-write-' + uuid.uuid4().hex
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=root)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, parts[-1], src_dir_fd=root, dst_dir_fd=root)
                os.fsync(root)
            finally:
                try:
                    os.unlink(temporary, dir_fd=root)
                except FileNotFoundError:
                    pass
            envelope(True, hashlib.sha256(payload).hexdigest().encode('ascii'))
        elif request['operation'] in ('git', 'git_read'):
            os.fchdir(root)
            env = os.environ.copy()
            env.update(GIT_TERMINAL_PROMPT='0', GIT_PAGER='cat', LC_ALL='C.UTF-8')
            command = ['git', '--no-pager', *request['args']]
            if request['operation'] == 'git_read':
                args = read_git_args(request['args'])
                metadata = open_directory(request['root']+'/.git')
                os.close(metadata)
                if os.environ.get('HOME') != '/home/agent':
                    raise ValueError('Expected role home required')
                if (any(key.startswith(('GIT_', 'LD_')) for key in os.environ)
                        or 'XDG_CONFIG_HOME' in os.environ or 'XDG_CONFIG_DIRS' in os.environ):
                    raise ValueError('Inherited Git or loader controls refused')
                env = {'PATH':'/usr/bin:/bin', 'HOME':'/home/agent', 'LC_ALL':'C.UTF-8',
                       'GIT_TERMINAL_PROMPT':'0', 'GIT_PAGER':'cat',
                       'GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':'/dev/null'}
                # Config enumeration invokes no repository hook/filter. Capture
                # it privately; only a bounded allowlisted configuration passes.
                def preflight(arguments):
                    child = subprocess.Popen(['/usr/bin/git', '--no-pager', *arguments],
                        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
                    poller = selectors.DefaultSelector()
                    result, total = [], 0
                    try:
                        poller.register(child.stdout, selectors.EVENT_READ, True)
                        poller.register(child.stderr, selectors.EVENT_READ, False)
                        while poller.get_map():
                            for event, _ in poller.select():
                                chunk = os.read(event.fileobj.fileno(), 65536)
                                if not chunk:
                                    poller.unregister(event.fileobj)
                                    continue
                                total += len(chunk)
                                if total > 65536:
                                    raise ValueError('Git preflight output exceeds limit')
                                if event.data:
                                    result.append(chunk)
                        if child.wait() != 0:
                            raise ValueError('Git preflight failed')
                        return b''.join(result)
                    finally:
                        poller.close()
                        if child.poll() is None:
                            child.kill()
                        child.wait()
                        child.stdout.close()
                        child.stderr.close()
                # Reject include directives themselves without following their
                # target files. No accepted config is changed or overridden.
                check_read_git_config(preflight(['config', '--null', '--list', '--no-includes']))
                entries = preflight(['ls-files', '--stage', '-z'])
                if any(entry.startswith(b'160000 ') for entry in entries.split(b'\0')):
                    raise ValueError('Submodule index not admitted in model VM')
                command = ['/usr/bin/git', '--no-pager', *args]
            proc = subprocess.Popen(command,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
            selector = selectors.DefaultSelector()
            output, errors, total = [], [], 0
            try:
                selector.register(proc.stdout, selectors.EVENT_READ, output)
                selector.register(proc.stderr, selectors.EVENT_READ, errors)
                while selector.get_map():
                    for key, _ in selector.select():
                        chunk = os.read(key.fileobj.fileno(), 65536)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        total += len(chunk)
                        if total > request['limit']:
                            raise ValueError('git output exceeds limit')
                        key.data.append(chunk)
                code = proc.wait()
                if code:
                    envelope(False, error='git returned ' + str(code))
                else:
                    envelope(True, b''.join(output))
            finally:
                selector.close()
                if proc.poll() is None:
                    proc.kill()
                proc.wait()
                proc.stdout.close()
                proc.stderr.close()
        else:
            raise ValueError('unknown operation')
    finally:
        os.close(root)
except FileNotFoundError:
    # A missing root is not an absent repository file. Root must have opened.
    if request['operation'] == 'fingerprint' and 'root' in locals():
        envelope(True, b'')
    elif request['operation'] == 'kind' and 'root' in locals():
        envelope(True, b'missing')
    else:
        envelope(False, error='FileNotFoundError')
except Exception as exc:
    # Do not leak file contents, arguments, credentials, or arbitrary exception text.
    envelope(False, error=type(exc).__name__)
'''


def _relative(value):
    if (not isinstance(value, str) or not value or '\x00' in value or '\\' in value
            or value.startswith('/') or any(p in ('', '.', '..') for p in value.split('/'))):
        raise ValueError('Normalized relative POSIX file path required')
    return value


def _limit(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 16 * 1024 * 1024:
        raise ValueError('Byte limit must be an integer from 1 to 16 MiB')
    return value


class GuestRepository:
    def __fspath__(self):
        raise TypeError('Guest repository is not a host filesystem path')

    def __str__(self):
        raise TypeError('Guest repository cannot be converted to a host command argument')

    def __init__(self, controller, guest_root, log_dir, *, timeout=120,
                 max_output_bytes=1024 * 1024, external_stop=None):
        if (not isinstance(guest_root, str) or not guest_root.startswith('/')
                or guest_root == '/' or '\x00' in guest_root or '\\' in guest_root
                or any(p in ('', '.', '..') for p in guest_root.split('/')[1:])
                or str(PurePosixPath(guest_root)) != guest_root):
            raise ValueError('Absolute normalized guest repository root required')
        if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
                or not math.isfinite(timeout) or timeout <= 0):
            raise ValueError('Finite positive timeout required')
        self.log_dir = Path(log_dir)
        if not self.log_dir.is_absolute():
            raise ValueError('Absolute controller-owned log directory required')
        self.controller, self.guest_root, self.timeout = controller, guest_root, timeout
        self.max_output_bytes = _limit(max_output_bytes)
        self.external_stop = Path(external_stop) if external_stop is not None else None
        self._model_read_only_git = False
        if self.external_stop is not None and not self.external_stop.is_absolute():
            raise ValueError('Absolute external STOP required')

    def _call(self, operation, limit, **parameters):
        # Even a git client which exited may have spawned descendants. Any
        # failed/ambiguous operation stops the whole owned VM, including a missing
        # file response. There is deliberately no implicit retry or resume.
        try:
            return self._call_unchecked(operation, limit, **parameters)
        except BaseException:
            self.controller.stop()
            raise

    def _call_unchecked(self, operation, limit, **parameters):
        request_id = uuid.uuid4().hex
        marker = 'EBASE_REPOSITORY_' + request_id + ':'
        request = dict(operation=operation, root=self.guest_root, limit=limit, **parameters)
        log_path = self.log_dir / ('repository-' + request_id + '.log')
        log_limit = ((limit + 2) // 3) * 4 + 65536
        extra = {'external_stop': self.external_stop} if self.external_stop is not None else {}
        result = self.controller.execute(
            ['python3', '-I', '-c', _GUEST_CODE, marker, json.dumps(request)],
            cwd='/', log_path=log_path, timeout=self.timeout, max_log_bytes=log_limit, **extra)
        if result.returncode != 0:
            raise GuestRepositoryError('Guest transport failed')
        # Permit bounded sbx startup banners, never read an arbitrary whole log.
        with log_path.open('rb') as stream:
            raw = stream.read(log_limit + 1)
        if len(raw) > log_limit:
            raise GuestRepositoryError('Guest response log exceeds limit')
        prefix = marker.encode('ascii')
        lines = [line[len(prefix):] for line in raw.splitlines() if line.startswith(prefix)]
        if len(lines) != 1:
            raise GuestRepositoryError('Missing or ambiguous guest response')
        def unique_keys(pairs):
            data = {}
            for key, value in pairs:
                if key in data:
                    raise ValueError('Duplicate response field')
                data[key] = value
            return data
        try:
            envelope = json.loads(lines[0], object_pairs_hook=unique_keys)
            if (not isinstance(envelope, dict) or set(envelope) != {'ok', 'data', 'error'}
                    or type(envelope['ok']) is not bool or not isinstance(envelope['data'], str)
                    or not isinstance(envelope['error'], str)):
                raise ValueError('Invalid envelope')
            data = base64.b64decode(envelope['data'], validate=True)
            if len(data) > limit or (envelope['ok'] and envelope['error']) or (not envelope['ok'] and data):
                raise ValueError('Invalid response payload')
        except (ValueError, TypeError, UnicodeError, binascii.Error, RecursionError) as exc:
            raise GuestRepositoryError('Malformed guest response') from exc
        if not envelope['ok']:
            raise GuestRepositoryError('Guest repository operation failed')
        return data

    def restrict_git_to_model_reads(self):
        """Irreversibly narrow this lease before model-phase Git operations."""
        self._model_read_only_git = True

    def git(self, *args):
        """Run caller-selected git arguments inside the VM; return strict UTF-8."""
        if (not args or len(args) > 1024 or any(not isinstance(a, str) or '\x00' in a for a in args)
                or sum(len(a) for a in args) > 65536):
            raise ValueError('Bounded git argument vector required')
        operation = 'git_read' if self._model_read_only_git else 'git'
        data = self._call(operation, self.max_output_bytes, args=list(args))
        try:
            return data.decode('utf-8')
        except UnicodeError as exc:
            self.controller.stop()
            raise GuestRepositoryError('Git output is not UTF-8') from exc

    def read_bytes(self, relative, max_bytes=1024 * 1024):
        return self._call('read', _limit(max_bytes), relative=_relative(relative))

    def snapshot_file(self, relative, max_bytes=1024 * 1024):
        """Read bytes and Git executable mode together, refusing linked files."""
        if type(max_bytes) is not int or not 1 <= max_bytes <= 1024 * 1024:
            raise ValueError('Snapshot file limit must be 1..1 MiB')
        raw = self._call('snapshot_read', max_bytes * 2 + 1024,
                         relative=_relative(relative), file_limit=max_bytes)
        try:
            def unique(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError('Duplicate snapshot field')
                    result[key] = value
                return result
            value = json.loads(raw, object_pairs_hook=unique)
            if (not isinstance(value, dict) or set(value) != {'mode', 'data'} or
                    value['mode'] not in ('100644', '100755') or not isinstance(value['data'], str)):
                raise ValueError('Malformed snapshot file')
            data = base64.b64decode(value['data'], validate=True)
            if len(data) > max_bytes:
                raise ValueError('Snapshot file exceeds bound')
            return {'mode': value['mode'], 'data': data}
        except (ValueError, TypeError, binascii.Error, RecursionError) as exc:
            self.controller.stop()
            raise GuestRepositoryError('Malformed snapshot file response') from exc

    def sha256(self, relative, max_bytes=1024 * 1024):
        return hashlib.sha256(self.read_bytes(relative, max_bytes)).hexdigest()

    def make_directory(self, relative):
        """Create a fresh leaf with safe parents; never reuse an existing leaf."""
        result = self._call('mkdir', 7, relative=_relative(relative))
        if result != b'created':
            self.controller.stop()
            raise GuestRepositoryError('Invalid directory acknowledgement')

    def path_kind(self, relative):
        """No-follow metadata check; absent paths are allowed for deletions."""
        result = self._call('kind', 16, relative=_relative(relative))
        if result not in (b'regular', b'missing', b'symlink', b'directory', b'hardlink', b'other'):
            self.controller.stop()
            raise GuestRepositoryError('Invalid path-kind response')
        return result.decode('ascii')

    def fingerprint(self, relative, max_bytes=16 * 1024 * 1024):
        """Digest a regular guest file, or None if absent; errors fence the VM.

        Unlike legacy host is_file(), links and special files are rejected.
        Requires a quiescent repository; not an atomic multi-file snapshot.
        """
        result = self._call('fingerprint', 64, relative=_relative(relative),
                            file_limit=_limit(max_bytes))
        if not result:
            return None
        if len(result) != 64 or any(c not in b'0123456789abcdef' for c in result):
            self.controller.stop()
            raise GuestRepositoryError('Invalid fingerprint response')
        return result.decode('ascii')

    def write_bytes(self, relative, payload):
        """Atomically replace a small non-secret file in existing guest parents.

        Payload travels in process arguments: never use for credentials. Large
        source/object transfer needs a separate streaming protocol. Existing
        regular files are replaced with mode 0600; executable mode is not kept.
        A guest digest is an acknowledgement, not trusted attestation.
        Requires a quiescent guest: no concurrent model/writer. If directory
        fsync fails after replacement, the write may already have committed;
        the failure fences the VM and must not be retried automatically.
        """
        relative = _relative(relative)
        if not isinstance(payload, bytes) or len(payload) > 32768:
            raise ValueError('Write requires at most 32 KiB of bytes')
        expected = hashlib.sha256(payload).hexdigest().encode('ascii')
        actual = self._call('write', 64, relative=relative,
                            payload=base64.b64encode(payload).decode('ascii'))
        if actual != expected:
            self.controller.stop()
            raise GuestRepositoryError('Write acknowledgement mismatch')

    def write_large_bytes(self, relative, payload):
        """Bounded non-secret chunk transfer, atomic destination replacement.

        Parts remain in a fresh sibling directory as recovery evidence. This is
        not automatic retry/resume and is not safe for concurrent guest writers.
        Payload chunks travel in argv; never transfer credentials this way.
        """
        relative = _relative(relative)
        if not isinstance(payload, bytes) or len(payload) > 16 * 1024 * 1024:
            raise ValueError('Transfer requires at most 16 MiB of bytes')
        if len(payload) <= 32768:
            return self.write_bytes(relative, payload)
        parent = relative.rpartition('/')[0]
        staging = (parent + '/' if parent else '') + '.transfer-' + uuid.uuid4().hex
        self.make_directory(staging)
        try:
            count = (len(payload) + 32767) // 32768
            for index in range(count):
                self.write_bytes(staging + '/' + str(index), payload[index * 32768:(index + 1) * 32768])
            expected = hashlib.sha256(payload).hexdigest()
            actual = self._call('assemble', 64, relative=relative, staging=staging,
                                count=count, size=len(payload), sha256=expected)
            if actual != expected.encode('ascii'):
                raise GuestRepositoryError('Transfer acknowledgement mismatch')
        except BaseException:
            self.controller.stop()
            raise
